from datetime import UTC, datetime, timedelta
import asyncio

import pytest
from pydantic import ValidationError

from app.terminal.analytics_inputs import AnalyticsInputStore, HistoricalAnalyticsInput
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def declared():
    now = datetime.now(UTC)
    dates = [now-timedelta(days=40-i) for i in range(40)]
    return dict(context=OptionsContext().model_dump(), provenance='User daily export', licence='Personal analysis', observed_at=now,
        bars=[dict(time=t,open=100+i,high=102+i,low=99+i,close=101+i,volume=1000) for i,t in enumerate(dates)],
        vix_history=[15+i/10 for i in range(40)], return_dates=dates, cash_flow_adjusted_returns=[.01,-.005]*20)


def test_import_owner_context_and_integrity(tmp_path):
    _,_,_,store = sources(tmp_path)
    records = AnalyticsInputStore(store)
    saved = records.save(7,declared())
    inputs,ref,value = records.load(7,saved['dataset_id'],OptionsContext())
    assert len(inputs['bars'])==40 and saved['checksum'] in ref
    assert saved['live_verification']=='unverified'
    with pytest.raises(ValueError): records.load(8,saved['dataset_id'],OptionsContext())
    with pytest.raises(ValueError): records.load(7,saved['dataset_id'],OptionsContext(underlying='BANKNIFTY'))


def test_invalid_history_is_rejected():
    raw = declared()
    raw['bars'][0]['high']=1
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['return_dates'].reverse()
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['cash_flow_adjusted_returns'][0]=float('nan')
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['return_dates'][1] = raw['return_dates'][0]+timedelta(minutes=1)
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)


def test_import_calculations_preserve_unverified_provenance(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    capture = AnalyticsCaptureService(market,store,snapshots,portfolio)
    async def run():
        result = await capture.capture(7,OptionsContext(),['get_technical_regime_snapshot','get_portfolio_attribution_and_rebalance'],
            budget=TurnBudget(),historical_input=declared())
        technical = result.for_role('options_trading_analysis')['get_technical_regime_snapshot']
        attribution = result.for_role('portfolio_analysis')['get_portfolio_attribution_and_rebalance']
        assert technical.metrics['ema20'] is not None
        assert attribution.metrics['observations']==40
        assert technical.coverage['input_provenance']=='user_declared_unverified'
        assert technical.status=='PARTIAL'
        assert any('declared by' in value for value in attribution.limitations)
    asyncio.run(run())


def test_authenticated_snapshot_accepts_validated_import(tmp_path):
    from fastapi.testclient import TestClient
    from test_analytics_route import application
    from app.terminal.analytics_inputs import HistoricalAnalyticsInput
    app, agent = application(tmp_path,True)
    payload = HistoricalAnalyticsInput.model_validate(declared()).model_dump(mode='json')
    with TestClient(app) as client:
        body = dict(role='portfolio_analysis',tools=['get_portfolio_attribution_and_rebalance'],historical_input=payload)
        reply = client.post('/api/options-agent/analytics/snapshot',json=body,headers={'x-test-auth':'yes'})
        assert reply.status_code==200
        assert reply.json()['evidence']['get_portfolio_attribution_and_rebalance']['metrics']['observations']==40
        payload['bars'][0]['high']=0
        assert client.post('/api/options-agent/analytics/snapshot',json=body,headers={'x-test-auth':'yes'}).status_code==422
