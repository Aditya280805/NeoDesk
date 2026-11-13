from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_store import AnalyticsStore
from app.terminal.options_agent import OptionsAgent
from app.terminal.routers.options_agent import options_agent_router
from test_analytics_capture import sources


def application(tmp_path,enabled):
    market,portfolio,snapshots,store = sources(tmp_path)
    agent = OptionsAgent.__new__(OptionsAgent)
    agent.config = SimpleNamespace(analytics_tools_enabled=enabled)
    agent.analytics_capture = AnalyticsCaptureService(market,store,snapshots,portfolio)
    agent.routing_limiter = Mock()
    app = FastAPI()
    app.state.options_agent = agent
    @app.middleware('http')
    async def identity(request,call_next):
        if request.headers.get('x-test-auth')=='yes':
            request.state.user = {'id':7}
        return await call_next(request)
    app.include_router(options_agent_router)
    return app,agent


def test_analytics_snapshot_auth_flag_and_role_projection(tmp_path):
    app,agent = application(tmp_path,True)
    with TestClient(app) as client:
        body = dict(role='options_trading_analysis',tools=['get_nse_oi_microstructure'],context={'expiry':'2026-11-17'})
        assert client.post('/api/options-agent/analytics/snapshot',json=body).status_code==401
        reply = client.post('/api/options-agent/analytics/snapshot',json=body,headers={'x-test-auth':'yes'})
        assert reply.status_code==200
        result = reply.json()
        assert result['evidence']['get_nse_oi_microstructure']['metrics']['pcr_oi']==2
        assert 'session-7' not in reply.text
        assert 'user_id' not in reply.text
        assert client.post('/api/options-agent/analytics/snapshot',json={**body,'tools':['check_sebi_and_mwpl_compliance']},headers={'x-test-auth':'yes'}).status_code==422
        assert client.post('/api/options-agent/analytics/snapshot',json={**body,'user_id':8},headers={'x-test-auth':'yes'}).status_code==422
        agent.config.analytics_tools_enabled=False
        assert client.post('/api/options-agent/analytics/snapshot',json=body,headers={'x-test-auth':'yes'}).status_code==404


def test_broker_failure_is_sanitized_and_releases_admission(tmp_path):
    app,agent = application(tmp_path,True)
    agent.analytics_capture.portfolio.assert_generation.side_effect = ValueError('secret-broker-token')
    with TestClient(app) as client:
        reply = client.post('/api/options-agent/analytics/snapshot',json={'role':'options_trading_analysis'},headers={'x-test-auth':'yes'})
        assert reply.status_code==503
        assert 'secret-broker-token' not in reply.text
    agent.routing_limiter.leave.assert_called_once_with(7)


def test_composite_rollout_is_independent_of_snapshot_tools(tmp_path):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from app.terminal.analytics_coordinator import dispatch_analytics
    _,agent=application(tmp_path,True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dispatch_analytics(agent,7,SimpleNamespace()))
    assert error.value.status_code==404
    agent.routing_limiter.enter.assert_not_called()
