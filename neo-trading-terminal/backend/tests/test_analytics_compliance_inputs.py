import asyncio
from datetime import UTC,datetime,timedelta

import pytest
from pydantic import ValidationError

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_inputs import HistoricalAnalyticsInput
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def declared():
    now = datetime.now(UTC)
    return dict(context=OptionsContext().model_dump(),provenance='Declared compliance scenario',licence='Personal use',observed_at=now,
        risk_positions=[dict(contract_id='future',underlying='NIFTY',kind='future',quantity=26,spot=100)],
        compliance_rules=[dict(contract_id='future',source='Declared dated exchange rule scenario',revision='scenario.1',
            instrument_scope='stock_derivative',valid_from=(now-timedelta(days=1)).date(),valid_until=now.date(),lot_size=25,ban_active=True,base_futeq=100,current_futeq=-50)])


def test_dated_compliance_scenario_detects_lot_and_sign_flip_without_healthy_verdict(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['check_sebi_and_mwpl_compliance'],budget=TurnBudget(),historical_input=declared())
        item = captured.for_role('portfolio_risk')['check_sebi_and_mwpl_compliance']
        assert item.metrics['risk_verdict']=='CANNOT_ASSESS'
        assert item.metrics['scenario_verdict']=='DECLARED_BREACH'
        assert any(f['code']=='lot_multiple' and f['outcome']=='breach' for f in item.metrics['findings'])
        assert any(f['reason']=='ban_delta_sign_reversal' for f in item.metrics['findings'])
        assert item.coverage['input_provenance']=='user_declared_unverified'
        assert item.metrics['rule_coverage'][0]['revision']=='scenario.1'
    asyncio.run(run())


def test_compliance_input_rejects_expired_unknown_and_client_verification_flags():
    raw = declared()
    raw['compliance_rules'][0]['valid_until']-=timedelta(days=3)
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['compliance_rules'][0]['contract_id']='other'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['compliance_rules'][0]['verified']=True
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['risk_positions'][0]['kind']='equity'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['compliance_rules'][0]['instrument_scope']='cash'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)


def test_api_reduction_stays_incomplete_and_index_scope_does_not_apply_stock_ban(tmp_path):
    from fastapi.testclient import TestClient
    from test_analytics_route import application
    raw = declared()
    raw['risk_positions'][0]['quantity']=25
    raw['compliance_rules'][0]['current_futeq']=50
    app,_ = application(tmp_path,True)
    with TestClient(app) as client:
        def request(payload):
            reply = client.post('/api/options-agent/analytics/snapshot',headers={'x-test-auth':'yes'},json={
                'role':'portfolio_risk','tools':['check_sebi_and_mwpl_compliance'],
                'historical_input':HistoricalAnalyticsInput.model_validate(payload).model_dump(mode='json')})
            assert reply.status_code==200
            return reply.json()['evidence']['check_sebi_and_mwpl_compliance']['metrics']
        metrics = request(raw)
        assert metrics['scenario_verdict']=='INCOMPLETE'
        assert metrics['risk_verdict']=='CANNOT_ASSESS'
        raw['compliance_rules'][0].update(instrument_scope='index_derivative',current_futeq=-50)
        metrics = request(raw)
        assert metrics['scenario_verdict']=='INCOMPLETE'
        assert any(finding['reason']=='stock_mwpl_rule_not_applicable_or_scope_unverified' for finding in metrics['findings'])
        raw['risk_positions'][0].update(kind='equity',quantity=26)
        raw['compliance_rules'][0]['instrument_scope']='cash'
        metrics = request(raw)
        assert metrics['scenario_verdict']=='INCOMPLETE'
        assert not any(finding['outcome']=='breach' for finding in metrics['findings'])
