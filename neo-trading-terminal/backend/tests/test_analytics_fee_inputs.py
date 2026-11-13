import asyncio
from datetime import UTC,datetime,timedelta

import pytest
from pydantic import ValidationError

from app.terminal.analytics_inputs import HistoricalAnalyticsInput
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def declared():
    return dict(context=OptionsContext().model_dump(),provenance='Declared transactions',licence='Personal use',observed_at=datetime.now(UTC),fee_transactions=[
        dict(transaction_id='old',product='option',side='SELL',turnover_inr='10000',turnover_basis='option_premium',trade_date='2026-03-31',cost_source='Declared broker rate scenario'),
        dict(transaction_id='new',product='option',side='SELL',turnover_inr='10000',turnover_basis='option_premium',trade_date='2026-04-01',cost_source='Declared broker rate scenario')])


def test_dated_fee_capture_preserves_unknown_cost_components(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['compute_indian_statutory_costs_and_payoff'],budget=TurnBudget(),historical_input=declared())
        item = captured.for_role('portfolio_analysis')['compute_indian_statutory_costs_and_payoff']
        fees = item.metrics['fee_estimate']
        assert [row['charges']['stt_paise'] for row in fees['transactions']]==[1000,1500]
        assert fees['total_paise'] is None
        assert fees['transactions'][0]['charges']['brokerage_paise'] is None
        assert item.metrics['gross_payoff'] is None
        assert item.coverage['input_provenance']=='user_declared_unverified'
        snapshots.fetch.assert_not_called()
    asyncio.run(run())


def test_fee_inputs_reject_wrong_basis_and_lossy_money():
    raw = declared()
    raw['fee_transactions'][0]['turnover_basis']='option_intrinsic'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['fee_transactions'][0]['turnover_inr']=10000.1
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['fee_transactions'][0]['trade_date']=(datetime.now(UTC)+timedelta(days=10)).date()
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)


def test_authenticated_fee_api_aggregates_only_explicit_components(tmp_path):
    from fastapi.testclient import TestClient
    from test_analytics_route import application
    raw = declared()
    raw['fee_transactions']=raw['fee_transactions'][1:]
    raw['fee_transactions'][0].update(brokerage_inr='20',exchange_rate='0.00035',sebi_rate='0.000001',slippage_inr='1')
    payload = HistoricalAnalyticsInput.model_validate(raw).model_dump(mode='json')
    app,_ = application(tmp_path,True)
    with TestClient(app) as client:
        response = client.post('/api/options-agent/analytics/snapshot',headers={'x-test-auth':'yes'},json={
            'role':'portfolio_analysis','tools':['compute_indian_statutory_costs_and_payoff'],'historical_input':payload})
        assert response.status_code==200
        item = response.json()['evidence']['compute_indian_statutory_costs_and_payoff']
        assert item['metrics']['fee_estimate']['total_paise']==4374
        assert item['metrics']['gross_payoff'] is None
        assert item['status']=='PARTIAL'
        assert 'session-7' not in response.text


def test_exercise_uses_intrinsic_basis_without_inventing_other_fees():
    from app.terminal.indian_charges import declared_fee_estimate
    raw = declared()
    raw['fee_transactions'][0].update(side='EXERCISE',turnover_basis='option_intrinsic')
    payload = HistoricalAnalyticsInput.model_validate(raw).model_dump(mode='json')
    result = declared_fee_estimate(payload['fee_transactions'])
    assert result['transactions'][0]['charges']['stt_paise']==1250
    assert result['transactions'][0]['charges']['itm_expiry_stt_trap_warning'] is True
    assert result['total_paise'] is None
