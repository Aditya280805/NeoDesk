import pytest
import asyncio
from unittest.mock import Mock, patch
from app.core.config import Settings
from app.terminal.store import Store
from app.terminal.market import Market
from app.terminal.paper import PaperAccount
from app.terminal.engine import StrategyEngine
from app.terminal.risk import RiskManager, RiskLimits

@pytest.fixture
def test_setup(tmp_path):
    config = Settings(
        data_dir=tmp_path,
        app_password=None,
        environment='development',
        frontend_url='http://localhost:3000'
    )
    store = Store(tmp_path / 'test.sqlite3', balance=500000)
    inst = {
        'id': 'nse_cm:INE002A01018',
        'symbol': 'RELIANCE',
        'name': 'Reliance Industries',
        'exchange': 'nse_cm',
        'kind': 'EQUITY',
        'underlying': '',
        'lot_size': 1,
        'tick_size': 0.05,
        'token': '2885',
        'exchange_token': '2885'
    }
    store.save_catalogue([inst], ['nse_cm'])
    
    # Needs a mock broker for market
    market = Market(config, store)
    market.broker = Mock()
    market.broker.client = Mock()
    market.source = 'test'
    
    paper = PaperAccount(store)
    rm = RiskManager(RiskLimits(max_order_value=50000.0))
    
    engine = StrategyEngine(store, market, paper, risk_manager=rm)
    return {'config': config, 'store': store, 'market': market, 'paper': paper, 'engine': engine, 'tmp_path': tmp_path, 'rm': rm}

@pytest.mark.anyio
async def test_e2e_paper_lifecycle(test_setup):
    engine = test_setup['engine']
    store = test_setup['store']
    
    sid = engine.deploy(
        instrument_id='nse_cm:INE002A01018',
        strategy_type='SMA_CROSSOVER',
        params={'fast': 3, 'slow': 5, 'cooldown_seconds': 0.0},
        initial=100000.0,
        mode='paper'
    )

    strat = engine.strategies[sid]
    # Warm up closes for SMA crossover
    strat['closes'] = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]

    # Tick 1: trigger BUY
    await engine.on_tick('2885', 120.0)
    
    signals = store.get_signals(strategy_id=sid)
    assert len(signals) == 1
    assert signals[0]['action'] == 'BUY'
    
    # Assert paper order was placed and filled
    orders = store.orders()
    assert len(orders) == 1
    assert orders[0]['side'] == 'BUY'
    assert orders[0]['status'] == 'FILLED'
    
    # Assert strategy held position updated
    assert strat['held'] > 0
    assert strat['cash'] < 100000.0
    
    # Tick 2: trigger SELL
    strat['closes'] = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 120.0, 121.0, 80.0]
    await engine.on_tick('2885', 60.0)
    
    signals_after = store.get_signals(strategy_id=sid)
    assert len(signals_after) == 2
    assert signals_after[0]['action'] == 'SELL'
    
    orders_after = store.orders()
    assert len(orders_after) == 2
    assert orders_after[0]['side'] == 'SELL'
    assert orders_after[0]['status'] == 'FILLED'
    
    assert strat['held'] == 0

@pytest.mark.anyio
async def test_e2e_live_guardrails_lifecycle(test_setup):
    engine = test_setup['engine']
    store = test_setup['store']
    market = test_setup['market']
    
    # Set limit low to trigger guardrail
    test_setup['rm'].limits = RiskLimits(max_order_value=1000.0)
    
    sid = engine.deploy(
        instrument_id='nse_cm:INE002A01018',
        strategy_type='SMA_CROSSOVER',
        params={'fast': 3, 'slow': 5, 'cooldown_seconds': 0.0},
        initial=100000.0,
        mode='live'
    )

    strat = engine.strategies[sid]
    strat['closes'] = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]

    # Place mock exception on live order execution just in case
    market.broker.client.place_order.side_effect = Exception("Live API Mock Error")

    with patch('app.websocket.manager.manager.broadcast') as mock_broadcast:
        # Tick 1: trigger BUY, but price is high and qty is large -> order value > 1000.0
        # Qty = cash / ltp = 100000 / 120 = 833. Value = 833 * 120 = 99960 > 1000
        # This should hit the RiskManager and reject the order before execution
        await engine.on_tick('2885', 120.0)
        
        # Verify signal generated but order rejected
        signals = store.get_signals(strategy_id=sid)
        assert len(signals) == 1
        assert signals[0]['action'] == 'BUY'
        
        # Guardrail should have caught it, strategy position shouldn't change
        # Wait, the engine currently updates strat['held'] BEFORE executing the order!
        # Let's check engine.py:
        # if signal.action == 'BUY' and strat['held'] == 0:
        #   qty = int(strat['cash'] / ltp)
        #   strat['held'] = qty
        #   strat['entry_cost'] = cost
        #   strat['cash'] -= cost
        #   await self._execute_order(strat, instrument, 'BUY', qty, ltp)
        
        # The test should reflect what the engine does, OR I should fix the engine.
        # The prompt says: "preserves the strategy position state accurately (it shouldn't think it holds position if order failed)."
        # Ah! I must fix engine.py to update position AFTER execution, or revert if execution fails!
