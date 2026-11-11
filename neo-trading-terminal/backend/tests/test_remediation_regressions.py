"""Regression tests for NeoDesk terminal security, isolation, broker, and config fixes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.auth.dependencies import get_request_user_id
from app.auth.router import _MAX_RATE_IPS, _check_rate_limit, _clear_rate_limits
from app.auth.service import create_token, decode_token
from app.brokers.base_broker import BrokerError
from app.brokers.paper_broker import PaperBroker
from app.core.config import Settings
from app.terminal.paper import PaperAccount
from app.terminal.server import create_app
from app.terminal.store import Store
from app.websocket.manager import ConnectionManager


@pytest.mark.anyio
async def test_connection_manager_requires_valid_user_and_blocks_none_broadcasts():
    cm = ConnectionManager()
    bad = MagicMock()
    bad.accept = AsyncMock()
    for invalid_uid in (None, False, True, 0, -1):
        with pytest.raises(ValueError):
            await cm.connect(bad, user_id=invalid_uid)
    assert bad.accept.call_count == 0

    alice = MagicMock()
    alice.accept = AsyncMock()
    alice.send_text = AsyncMock()
    orphan = MagicMock()
    orphan.send_text = AsyncMock()

    await cm.connect(alice, user_id=2)
    cm.active_connections.append(orphan)  # simulate unmapped socket without user_ids entry

    # Missing or None user_id must never default to user 1 or match unmapped None sockets.
    await cm.broadcast({'type': 'QUOTE', 'data': {'id': 'nse_cm|1333', 'ltp': 100}})
    await cm.broadcast({'type': 'QUOTE', 'data': {'id': 'nse_cm|1333', 'ltp': 100}, 'user_id': None})
    assert alice.send_text.call_count == 0
    assert orphan.send_text.call_count == 0

    # Valid broadcast targets Alice and sweeps orphan sockets.
    await cm.broadcast({'type': 'SIGNAL', 'data': {'price': 101}, 'user_id': 2})
    assert alice.send_text.call_count == 1
    assert orphan not in cm.active_connections


def test_paper_broker_vwap_partial_close_flip_defensive_copies_and_validation():
    broker = PaperBroker()

    # Mutating returned quotes/orders/positions must not corrupt internal broker state.
    quotes = broker.get_quotes()
    quotes[0]['ltp'] = -999
    assert broker.get_quotes()[0]['ltp'] > 0

    # Invalid inputs rejected strictly
    for bad_order in (
        {'symbol': '', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1, 'price': 100},
        {'symbol': 'INFY', 'side': 'SHORT', 'order_type': 'MARKET', 'quantity': 1, 'price': 100},
        {'symbol': 'INFY', 'side': 'BUY', 'order_type': 'STOP', 'quantity': 1, 'price': 100},
        {'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 0, 'price': 100},
        {'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': True, 'price': 100},
        {'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1, 'price': 0},
        {'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1, 'price': float('nan')},
    ):
        with pytest.raises(BrokerError):
            broker.place_order(bad_order)

    # Buy 10 @ 100 + Buy 10 @ 200 -> VWAP 150.0
    o1 = broker.place_order({'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 10, 'price': 100.0})
    o1['status'] = 'TAMPERED'
    assert broker.get_orders()[0]['status'] == 'FILLED'
    broker.place_order({'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 10, 'price': 200.0})
    pos = broker.get_positions()[0]
    assert pos['quantity'] == 20 and pos['average_price'] == 150.0 and pos['pnl'] == 0.0

    # Partial sell 10 @ 180 -> qty 10, avg preserved at 150.0, realized pnl = 300.0
    broker.place_order({'symbol': 'INFY', 'side': 'SELL', 'order_type': 'MARKET', 'quantity': 10, 'price': 180.0})
    pos = broker.get_positions()[0]
    assert pos['quantity'] == 10 and pos['average_price'] == 150.0 and pos['pnl'] == 300.0

    # Flip across zero: sell 25 @ 170 (closes 10 @ 170 -> +200, opens -15 @ 170 -> total pnl 500)
    broker.place_order({'symbol': 'INFY', 'side': 'SELL', 'order_type': 'MARKET', 'quantity': 25, 'price': 170.0})
    pos = broker.get_positions()[0]
    assert pos['quantity'] == -15 and pos['average_price'] == 170.0 and pos['pnl'] == 500.0

    # Full close of short: buy 15 @ 160 -> +150 -> total pnl 650, qty 0, avg 0.0
    broker.place_order({'symbol': 'INFY', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 15, 'price': 160.0})
    pos = broker.get_positions()[0]
    assert pos['quantity'] == 0 and pos['average_price'] == 0.0 and pos['pnl'] == 650.0


def test_paper_broker_concurrent_reads_and_writes():
    broker = PaperBroker()

    def worker(idx: int):
        for i in range(10):
            broker.place_order({'symbol': 'RELIANCE', 'side': 'BUY', 'order_type': 'MARKET', 'quantity': 1, 'price': 100.0 + (idx + i)})
            broker.get_positions()
            broker.get_orders()
            broker.get_quotes()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
    pos = broker.get_positions()[0]
    assert pos['quantity'] == 40
    assert len(broker.get_orders()) == 40


def test_paper_account_missing_user_never_leaks_user1_and_validates_inputs(tmp_path):
    store = Store(tmp_path / 'db.sqlite3', 100000)
    paper = PaperAccount(store)

    # User 99 has no account row; must see zero balance rather than user 1's 100000 balance.
    snap = paper.snapshot(99, {})
    assert snap['initial'] == 0 and snap['cash'] == 0 and snap['available'] == 0

    item = {'id': 'nse_cm|1333', 'symbol': 'HDFCBANK', 'exchange': 'nse_cm', 'kind': 'EQUITY', 'lot_size': 1, 'tick_size': '0.05'}
    quote = {'source': 'demo', 'ltp': 100.0}
    for kwargs, msg in (
        ({'side': 'SHORT', 'quantity': 1, 'order_type': 'MARKET'}, 'Order side'),
        ({'side': 'BUY', 'quantity': 1, 'order_type': 'STOP'}, 'Order type'),
        ({'side': 'BUY', 'quantity': True, 'order_type': 'MARKET'}, 'positive integer'),
        ({'side': 'BUY', 'quantity': 1, 'order_type': 'LIMIT', 'price': None}, 'limit price'),
    ):
        with pytest.raises(ValueError, match=msg):
            paper.submit(item, request_id='req-1', quote=quote, user_id=1, **kwargs)

    fut = {'id': 'nse_fo|9999', 'symbol': 'NIFTYFUT', 'exchange': 'nse_fo', 'kind': 'FUTURE', 'lot_size': 25, 'tick_size': '0.05'}
    with pytest.raises(ValueError, match='Order side'):
        paper.submit(fut, side='HOLD', quantity=25, order_type='MARKET', price=None, request_id='req-2', quote=quote, user_id=1)


def test_legacy_account_check_constraint_migrates_for_multi_user(tmp_path):
    db_path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.executescript('''
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                user_id INTEGER DEFAULT 1,
                initial INTEGER,
                cash INTEGER,
                realized INTEGER DEFAULT 0
            );
            INSERT INTO account (id, user_id, initial, cash, realized) VALUES (1, 1, 10000000, 9500000, 500);
            INSERT INTO metadata VALUES ('multi_user_v1', '1');
        ''')

    store = Store(db_path, 100000)
    store.init_user_account(2, 100000)
    store.init_user_account(3, 250000)

    with store.connect() as db:
        rows = {r['user_id']: dict(r) for r in db.execute('SELECT * FROM account').fetchall()}
    assert rows[1]['cash'] == 9500000 and rows[1]['realized'] == 500
    assert rows[2]['cash'] == 10000000
    assert rows[3]['cash'] == 25000000


def test_sync_requires_kotak_returns_400_and_isolates_sync_status_per_user(tmp_path, monkeypatch):
    _clear_rate_limits()
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='test',
                              app_password=None, market_data_source='sample', kotak_consumer_key=None))

    def broken_sync(user_id: int):
        raise BrokerError('upstream down')

    monkeypatch.setattr(app.state.market, 'sync', broken_sync)
    with TestClient(app, headers={'X-NeoDesk': '1'}) as client:
        tok_a = client.post('/api/auth/register', json={
            'email': 'sync_a@example.com', 'password': 'password123', 'display_name': 'Alice'
        }).json()['access_token']
        tok_b = client.post('/api/auth/register', json={
            'email': 'sync_b@example.com', 'password': 'password123', 'display_name': 'Bob'
        }).json()['access_token']
        ha = {'Authorization': f'Bearer {tok_a}', 'X-NeoDesk': '1'}
        hb = {'Authorization': f'Bearer {tok_b}', 'X-NeoDesk': '1'}

        # Global market.source='kotak' must NOT allow unconfigured Bob (user 3) to sync.
        app.state.market.source = 'kotak'
        res_bob = client.post('/api/instruments/sync', headers=hb)
        assert res_bob.status_code == 400
        assert res_bob.json()['detail'] == 'Connect Kotak first.'

        # Connect Kotak session specifically for Alice.
        with client.app.state.market.lock:
            pass
        app.state.market.get_session(2).source = 'kotak'

        res_alice = client.post('/api/instruments/sync', headers=ha)
        assert res_alice.status_code == 202

        # Allow background task a moment to complete/fail cleanly.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            st_a = client.get('/api/status', headers=ha).json()['catalogue_sync']
            if not st_a['running']:
                break
            time.sleep(0.02)

        st_a = client.get('/api/status', headers=ha).json()['catalogue_sync']
        st_b = client.get('/api/status', headers=hb).json()['catalogue_sync']
        assert st_a['running'] is False and st_a['error'] is not None
        assert st_b == {'running': False, 'error': None}

        # Lock must have been released so retrying does not stick at 409.
        assert client.post('/api/instruments/sync', headers=ha).status_code == 202


def test_market_sync_audits_initiating_user_id(tmp_path, monkeypatch):
    import app.terminal.market as market_mod

    store = Store(tmp_path / 'audit.sqlite3', 100000)
    cfg = Settings(_env_file=None, data_dir=tmp_path, environment='test', app_password=None, kotak_consumer_key=None)
    mkt = market_mod.Market(cfg, store)

    monkeypatch.setattr(mkt, 'call', lambda method, user_id=1, **kw: f'https://lapi.kotaksecurities.com/master/{kw["exchange_segment"]}.csv')
    monkeypatch.setattr(market_mod, 'parse_master', lambda text, seg: [])
    monkeypatch.setattr(store, 'save_catalogue', lambda rows, segs: None)

    class FakeResp:
        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b'header\n'

    @contextmanager
    def fake_stream(*args, **kwargs):
        yield FakeResp()

    monkeypatch.setattr(market_mod.httpx, 'stream', fake_stream)
    mkt.sync(user_id=7)
    with store.connect() as db:
        row = db.execute("SELECT user_id, event FROM audit WHERE event='catalogue_sync'").fetchone()
    assert row['user_id'] == 7


def test_rate_limiter_evicts_stale_ips_and_bounds_cache():
    attempts = {f'10.0.0.{i}': [time.time() - 120] for i in range(1200)}
    _check_rate_limit(attempts, '192.168.1.1', 5, 'login')
    # All expired keys are purged once threshold is crossed.
    assert list(attempts.keys()) == ['192.168.1.1']

    now = time.time()
    bounded = {f'10.1.{i // 250}.{i % 250}': [now] for i in range(_MAX_RATE_IPS)}
    _check_rate_limit(bounded, '203.0.113.5', 5, 'login')
    assert len(bounded) <= _MAX_RATE_IPS
    assert '203.0.113.5' in bounded


def test_jwt_secret_persists_across_restarts_and_production_rejects_short_secret(tmp_path):
    cfg1 = Settings(_env_file=None, data_dir=tmp_path, environment='test', app_password=None)
    cfg2 = Settings(_env_file=None, data_dir=tmp_path, environment='test', app_password=None)
    assert cfg1.jwt_secret == cfg2.jwt_secret
    assert (tmp_path / '.jwt_secret').exists()

    tok = create_token(2, 'restart@example.com', cfg1.jwt_secret)
    assert decode_token(tok, cfg2.jwt_secret)['user_id'] == 2

    with pytest.raises(RuntimeError):
        create_app(Settings(_env_file=None, data_dir=tmp_path, environment='production',
                            app_password='a-long-private-password', jwt_secret='too-short'))


def test_get_request_user_id_never_silently_defaults_to_user1():
    scope = {'type': 'http', 'method': 'GET', 'path': '/api/paper', 'headers': []}
    req = Request(scope)
    with pytest.raises(HTTPException) as exc:
        get_request_user_id(req)
    assert exc.value.status_code == 401

    req.state.legacy_user_id = 1
    assert get_request_user_id(req) == 1

    req.state.user = {'id': 42}
    assert get_request_user_id(req) == 42


def test_websocket_rejects_unauthenticated_in_development_and_cleans_up_on_disconnect(tmp_path):
    dev_app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='development',
                                  app_password=None, market_data_source='sample', kotak_consumer_key=None))
    with TestClient(dev_app, headers={'X-NeoDesk': '1'}) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/ws/stream'):
                pass

        res = client.post('/api/auth/register', json={
            'email': 'ws_cleanup@example.com', 'password': 'password123', 'display_name': 'WS User'
        }).json()
        with client.websocket_connect(f"/api/ws/stream?token={res['access_token']}"):
            pass

    from app.websocket.manager import manager
    assert len(manager.active_connections) == 0
