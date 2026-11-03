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
        _env_file=None,
        data_dir=tmp_path,
        app_password=None,
        environment='test',
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
    
    with pytest.raises(ValueError,match='Automated live strategies are unavailable'):
        engine.deploy(instrument_id='nse_cm:INE002A01018',mode='live')
    assert store.list_strategies()==[]
    assert store.orders()==[]
    market.broker.client.place_order.assert_not_called()
