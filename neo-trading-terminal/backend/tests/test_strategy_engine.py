import pytest
from pathlib import Path
from starlette.testclient import TestClient
from app.core.config import Settings
from app.terminal.store import Store
from app.terminal.market import Market
from app.terminal.paper import PaperAccount
from app.terminal.engine import StrategyEngine
from app.terminal.server import create_app

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
    # Populate a test instrument
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
    market = Market(config, store)
    paper = PaperAccount(store)
    engine = StrategyEngine(store, market, paper)
    return {'config': config, 'store': store, 'market': market, 'paper': paper, 'engine': engine, 'tmp_path': tmp_path}

@pytest.mark.anyio
async def test_strategy_engine_deploy_and_persistence(test_setup):
    engine = test_setup['engine']
    store = test_setup['store']
    
    # Deploy SMA strategy
    sid1 = engine.deploy(
        instrument_id='nse_cm:INE002A01018',
        strategy_type='SMA_CROSSOVER',
        params={'fast': 3, 'slow': 5, 'cooldown_seconds': 0.0},
        initial=50000.0,
        mode='paper',
        name='Reliance Fast SMA'
    )
    assert sid1 is not None

    # Verify persisted in SQLite
    saved = store.get_strategy(sid1)
    assert saved is not None
    assert saved['name'] == 'Reliance Fast SMA'
    assert saved['strategy_type'] == 'SMA_CROSSOVER'
    assert saved['status'] == 'RUNNING'
    assert saved['cash'] == 50000.0

    # Test engine re-instantiation restores the strategy
    engine2 = StrategyEngine(store, test_setup['market'], test_setup['paper'])
    active = engine2.list_active()
    assert any(s['id'] == sid1 for s in active)

    # Stop strategy
    engine2.stop(sid1)
    saved2 = store.get_strategy(sid1)
    assert saved2['status'] == 'STOPPED'

@pytest.mark.anyio
async def test_strategy_engine_tick_and_signals(test_setup):
    engine = test_setup['engine']
    store = test_setup['store']
    
    sid = engine.deploy(
        instrument_id='nse_cm:INE002A01018',
        strategy_type='SMA_CROSSOVER',
        params={'fast': 3, 'slow': 5, 'cooldown_seconds': 0.0},
        initial=100000.0,
        mode='paper'
    )

    # Manually populate warm closes to simulate golden cross
    strat = engine.strategies[sid]
    strat['closes'] = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]

    # Ingest tick that causes fast to cross above slow -> triggers BUY signal
    await engine.on_tick('2885', 120.0)

    # Check signal recorded in store
    signals = store.get_signals(strategy_id=sid)
    assert len(signals) >= 1
    assert signals[0]['action'] == 'BUY'
    assert signals[0]['price'] == 120.0
    assert strat['held'] > 0

    # Ingest subsequent ticks that plunge price -> triggers SELL signal
    strat['closes'] = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 120.0, 121.0, 80.0]
    await engine.on_tick('2885', 60.0)

    signals_after = store.get_signals(strategy_id=sid)
    assert len(signals_after) >= 2
    assert signals_after[0]['action'] == 'SELL'
    assert strat['held'] == 0

def test_strategy_api_endpoints(test_setup):
    config = test_setup['config']
    app = create_app(config)
    client = TestClient(app)

    # 1. Deploy strategy via REST
    deploy_payload = {
        'instrument_id': 'nse_cm:INE002A01018',
        'name': 'API Bot Test',
        'strategy_type': 'RSI_EXTREME',
        'params': {'period': 14, 'oversold': 30, 'overbought': 70},
        'initial': 75000,
        'mode': 'paper'
    }
    res = client.post('/api/strategies/deploy', json=deploy_payload, headers={'X-NeoDesk': '1'})
    assert res.status_code == 200
    data = res.json()
    assert 'id' in data
    sid = data['id']

    # 2. Get active strategies
    res = client.get('/api/strategies/active')
    assert res.status_code == 200
    active = res.json()
    assert any(s['id'] == sid for s in active)

    # 3. Get single strategy details
    res = client.get(f'/api/strategies/{sid}')
    assert res.status_code == 200
    assert res.json()['name'] == 'API Bot Test'

    # 4. Get signals history
    res = client.get(f'/api/strategies/{sid}/signals')
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 5. Get recent global signals
    res = client.get('/api/signals/recent')
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 6. Stop strategy
    res = client.delete(f'/api/strategies/{sid}', headers={'X-NeoDesk': '1'})
    assert res.status_code == 200
    assert res.json()['ok'] is True
