import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.terminal.analytics_inputs import HistoricalAnalyticsInput
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def risk_input(count=301):
    now = datetime.now(UTC)
    return dict(context=OptionsContext().model_dump(),provenance='User adjusted daily series',licence='Personal use',observed_at=now,
        risk_positions=[dict(contract_id='cash-index',underlying='NIFTY',kind='equity',quantity=10,spot=100)],
        risk_history={'cash-index':[dict(date=(now-timedelta(days=count-i)).date().isoformat(),session=i,spot=100+i/10) for i in range(count)]},
        risk_history_basis='current_contract_equivalent_source_declared')


def test_imported_risk_snapshot_keeps_95_when_99_history_is_short(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    service = AnalyticsCaptureService(market,store,snapshots,portfolio)
    async def run():
        captured = await service.capture(7,OptionsContext(),['run_spot_vix_cvar_stress_matrix'],budget=TurnBudget(),historical_input=risk_input())
        evidence = captured.for_role('portfolio_risk')['run_spot_vix_cvar_stress_matrix']
        assert len(evidence.metrics['cells'])==28
        tails = evidence.metrics['historical_tail']
        for scope in (tails['portfolio'],tails['instruments']['cash-index']):
            for horizon in ('1d','5d'):
                assert scope[horizon]['cvar_95'] is not None
                assert scope[horizon]['cvar_99'] is None
                assert scope[horizon]['unavailable_reasons']['cvar_99']=='insufficient_history_for_99pct'
        assert evidence.coverage['input_provenance']=='user_declared_unverified'
        assert evidence.metrics['risk_verdict']=='CANNOT_ASSESS'
        snapshots.fetch.assert_not_called()
    asyncio.run(run())


def test_risk_import_rejects_nonconsecutive_sessions_cross_context_and_bad_values():
    raw = risk_input()
    raw['risk_history']['cash-index'][1]['session']=9
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = risk_input()
    raw['risk_positions'][0]['underlying']='BANKNIFTY'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = risk_input()
    raw['risk_positions'][0]['quantity']=True
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = risk_input()
    raw['risk_history_basis']=None
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)


def test_option_history_reprices_and_preserves_per_series_coverage(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    raw = risk_input(1006)
    raw['risk_positions'].append(dict(contract_id='option',underlying='NIFTY',kind='option',quantity=-25,spot=100,
        forward=101,strike=100,expiry_at=raw['observed_at']+timedelta(days=73),iv=.25,rate=.05,option_type='CALL'))
    raw['risk_history']['option'] = [{**row,'iv':.2+(i%20)/1000} for i,row in enumerate(raw['risk_history']['cash-index'][:301])]
    service = AnalyticsCaptureService(market,store,snapshots,portfolio)
    async def run():
        captured = await service.capture(7,OptionsContext(),['run_spot_vix_cvar_stress_matrix'],budget=TurnBudget(),historical_input=raw)
        tails = captured.for_role('portfolio_risk')['run_spot_vix_cvar_stress_matrix'].metrics['historical_tail']
        assert tails['instruments']['cash-index']['5d']['cvar_99'] is not None
        assert tails['instruments']['option']['5d']['cvar_95'] is not None
        assert tails['instruments']['option']['5d']['cvar_99'] is None
        assert tails['portfolio']['5d']['scenario_count']==296
    asyncio.run(run())


def test_authenticated_risk_import_api_preserves_partial_tail_availability(tmp_path):
    from fastapi.testclient import TestClient
    from test_analytics_route import application
    app,_ = application(tmp_path,True)
    payload = HistoricalAnalyticsInput.model_validate(risk_input()).model_dump(mode='json')
    with TestClient(app) as client:
        response = client.post('/api/options-agent/analytics/snapshot',headers={'x-test-auth':'yes'},json={
            'role':'portfolio_risk','tools':['run_spot_vix_cvar_stress_matrix'],'historical_input':payload})
        assert response.status_code==200
        result = response.json()['evidence']['run_spot_vix_cvar_stress_matrix']
        assert result['metrics']['historical_tail']['portfolio']['1d']['var_95'] is not None
        assert result['metrics']['historical_tail']['portfolio']['1d']['var_99'] is None
        assert 'session-7' not in response.text
