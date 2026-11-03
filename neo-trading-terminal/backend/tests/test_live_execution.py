import pytest
import asyncio
from unittest.mock import Mock, patch, PropertyMock
from fastapi.testclient import TestClient

# The fixture supplies an isolated app; importing app.main would open the real database.
app = None
from app.terminal.risk import RiskManager, RiskLimits, RiskViolationError
from app.terminal.engine import StrategyEngine
from app.core.config import Settings
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker

@pytest.fixture(autouse=True)
def reset_app_state(tmp_path,monkeypatch):
    import sys
    from app.terminal.server import create_app
    from app.auth.router import _clear_rate_limits
    isolated=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,
                                 market_data_source='sample',kotak_consumer_key=None,live_trading_enabled=True))
    monkeypatch.setattr(sys.modules[__name__],'app',isolated)
    _clear_rate_limits()
    app.state.risk_manager.reset_kill_switch()
    app.state.risk_manager.limits = RiskLimits()
    yield

@pytest.fixture
def test_client():
    with TestClient(app) as client:
        client.headers.update({"X-NeoDesk": "1"})
        result=client.post('/api/auth/register',json={'email':'risk@example.com','password':'password123','display_name':'Risk tester'})
        assert result.status_code==200
        yield client

def test_manual_live_order_blocked_by_risk(test_client):
    app.state.risk_manager.limits.max_order_value = 1000.0
    
    with patch.object(KotakNeoBroker, 'is_authenticated', new_callable=PropertyMock) as mock_auth:
        mock_auth.return_value = True
        
        # Mock store to return a dummy instrument
        app.state.store.instrument = Mock(return_value={'id':'RELIANCE','symbol': 'RELIANCE', 'exchange': 'nse_cm','kind':'EQUITY','tick_size':.05})
        
        # Mock market.quotes to return a high LTP
        app.state.market.quotes = Mock(return_value=[{'ltp': 2000.0,'source':'kotak'}])
        
        response = test_client.post("/api/live/orders", json={
            "instrument_id": "RELIANCE",
            "side": "BUY",
            "quantity": 2, # Value = 4000
            "order_type": "MARKET",
            "request_id": "00000000-0000-0000-0000-000000000000"
        })
        
        assert response.status_code == 400
        assert "Risk Guardrail Violation" in response.json()["detail"]
        assert "Order value 4000.0 exceeds max 1000.0" in response.json()["detail"]

def test_manual_live_order_kill_switch(test_client):
    app.state.risk_manager.trigger_kill_switch("Emergency stop")
    
    with patch.object(KotakNeoBroker, 'is_authenticated', new_callable=PropertyMock) as mock_auth:
        mock_auth.return_value = True
        app.state.store.instrument = Mock(return_value={'id':'RELIANCE','symbol': 'RELIANCE', 'exchange': 'nse_cm','kind':'EQUITY','tick_size':.05})
        app.state.market.quotes = Mock(return_value=[{'ltp': 100.0,'source':'kotak'}])
        
        response = test_client.post("/api/live/orders", json={
            "instrument_id": "RELIANCE",
            "side": "BUY",
            "quantity": 1, 
            "order_type": "MARKET",
            "request_id": "00000000-0000-0000-0000-000000000000"
        })
        
        assert response.status_code == 400
        assert "Kill switch is active" in response.json()["detail"]

@pytest.mark.anyio
async def test_legacy_live_strategy_cannot_submit_an_order():
    mock_store = Mock()
    mock_store.list_strategies.return_value=[]
    mock_market = Mock()
    mock_paper = Mock()
    engine = StrategyEngine(mock_store,mock_market,mock_paper)
    strat={'id':'old-live-strategy','mode':'live','instrument_id':'TCS'}
    assert await engine._execute_order(strat,{'symbol':'TCS'},'BUY',1,50) is False
    mock_market.call.assert_not_called()
    mock_market.broker.client.place_order.assert_not_called()
    mock_paper.submit.assert_not_called()

def test_risk_api_endpoints(test_client):
    # Status
    res = test_client.get("/api/risk/status")
    assert res.status_code == 200
    assert res.json()["kill_switch_active"] == False
    
    # Trigger kill switch
    res = test_client.post("/api/risk/kill-switch", json={"reason": "Testing"})
    assert res.status_code == 200
    assert res.json()["kill_switch_active"] == True
    
    # Reset kill switch
    res = test_client.post("/api/risk/reset-kill-switch")
    assert res.status_code == 200
    assert res.json()["kill_switch_active"] == False
    
    # Update limits
    res = test_client.put("/api/risk/limits", json={
        "max_order_value": 9999.0,
        "max_daily_loss": 5000.0,
        "max_price_deviation_pct": 5.0,
        "max_quantity_per_order": 500
    })
    assert res.status_code == 200
    assert res.json()["limits"]["max_order_value"] == 9999.0
