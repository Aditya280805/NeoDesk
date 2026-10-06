import pytest
import asyncio
from unittest.mock import Mock, patch, PropertyMock
from fastapi.testclient import TestClient

from app.main import app
from app.terminal.risk import RiskManager, RiskLimits, RiskViolationError
from app.terminal.engine import StrategyEngine
from app.core.config import Settings
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker

@pytest.fixture(autouse=True)
def reset_app_state():
    app.state.risk_manager.reset_kill_switch()
    app.state.risk_manager.limits = RiskLimits()
    yield

@pytest.fixture
def test_client():
    with TestClient(app) as client:
        client.headers.update({"X-NeoDesk": "1"})
        yield client

def test_manual_live_order_blocked_by_risk(test_client):
    app.state.risk_manager.limits.max_order_value = 1000.0
    
    with patch.object(KotakNeoBroker, 'is_authenticated', new_callable=PropertyMock) as mock_auth:
        mock_auth.return_value = True
        
        # Mock store to return a dummy instrument
        app.state.store.instrument = Mock(return_value={'symbol': 'RELIANCE', 'exchange': 'nse_cm'})
        
        # Mock market.quotes to return a high LTP
        app.state.market.quotes = Mock(return_value=[{'ltp': 2000.0}])
        
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
        app.state.store.instrument = Mock(return_value={'symbol': 'RELIANCE', 'exchange': 'nse_cm'})
        app.state.market.quotes = Mock(return_value=[{'ltp': 100.0}])
        
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
async def test_automated_strategy_live_execution():
    rm = RiskManager(RiskLimits(max_order_value=1000.0))
    mock_store = Mock()
    mock_market = Mock()
    mock_paper = Mock()
    
    engine = StrategyEngine(mock_store, mock_market, mock_paper, risk_manager=rm)
    
    # Mock broadcast
    with patch('app.websocket.manager.manager.broadcast') as mock_broadcast:
        # Mock broker place_order
        mock_market.broker.client.place_order = Mock(return_value={'nOrdNo': '12345'})
        
        strat = {
            'id': 'test-strat',
            'mode': 'live',
            'instrument_id': 'TCS'
        }
        instrument = {'symbol': 'TCS', 'exchange': 'nse_cm', 'neo_symbol': 'TCS-EQ'}
        
        # Test 1: Valid order (value 10 * 50 = 500)
        await engine._execute_order(strat, instrument, 'BUY', 10, 50.0)
        
        mock_market.broker.client.place_order.assert_called_once()
        mock_broadcast.assert_not_called()
        
        # Reset mock
        mock_market.broker.client.place_order.reset_mock()
        
        # Test 2: Invalid order (value 10 * 150 = 1500)
        await engine._execute_order(strat, instrument, 'BUY', 10, 150.0)
        
        mock_market.broker.client.place_order.assert_not_called()
        mock_broadcast.assert_called_once()
        args, kwargs = mock_broadcast.call_args
        assert args[0]['type'] == 'RISK_ALERT'
        assert args[0]['data']['strategy_id'] == 'test-strat'

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
