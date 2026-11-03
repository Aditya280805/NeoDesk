"""Account and workflow regressions found during the October codebase review."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.router import _clear_rate_limits
from app.core.config import Settings
from app.terminal.server import create_app


@pytest.fixture
def accounts(tmp_path):
    _clear_rate_limits()
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',
                            app_password=None,market_data_source='sample',kotak_consumer_key=None))
    with TestClient(app,headers={'X-NeoDesk':'1'},raise_server_exceptions=False) as client:
        headers=[]
        for name in ('alice','bob'):
            result=client.post('/api/auth/register',json={'email':name+'@example.com',
                'password':'review-password-123','display_name':name})
            assert result.status_code==200
            headers.append({'Authorization':'Bearer '+result.json()['access_token']})
        yield app,client,*headers


def test_stop_orders_without_body_is_account_scoped(accounts):
    app,client,alice,bob=accounts
    response=client.post('/api/risk/kill-switch',headers=alice)
    assert response.status_code==200
    assert response.json()['kill_switch_active'] is True
    assert client.get('/api/risk/status',headers=bob).json()['kill_switch_active'] is False
    assert client.post('/api/risk/reset-kill-switch',headers=alice).status_code==200
    assert client.get('/api/risk/status',headers=alice).json()['kill_switch_active'] is False


def test_risk_limits_reject_negative_values_and_remain_private(accounts):
    app,client,alice,bob=accounts
    assert client.put('/api/risk/limits',headers=alice,json={'max_order_value':-1}).status_code==422
    response=client.put('/api/risk/limits',headers=alice,json={'max_order_value':1234})
    assert response.status_code==200
    assert client.get('/api/risk/status',headers=alice).json()['limits']['max_order_value']==1234
    assert client.get('/api/risk/status',headers=bob).json()['limits']['max_order_value']==500000


def test_paper_order_retry_ids_are_private_to_each_account(accounts):
    app,client,alice,bob=accounts
    body={'instrument_id':'nse_cm|1333','side':'BUY','quantity':1,
          'order_type':'MARKET','request_id':str(uuid4())}
    first=client.post('/api/paper/orders',headers=alice,json=body)
    second=client.post('/api/paper/orders',headers=bob,json=body)
    assert first.status_code==second.status_code==201
    assert first.json()['id']!=second.json()['id']
    assert len(client.get('/api/paper',headers=bob).json()['positions'])==1
    assert client.post('/api/paper/orders',headers=bob,json=body).json()['id']==second.json()['id']


def test_backtest_uses_authenticated_users_market_session(accounts,monkeypatch):
    app,client,alice,bob=accounts
    actual=app.state.market.history
    seen=[]
    def history(*args,**kwargs):
        seen.append(kwargs.get('user_id',1))
        return actual(*args,**kwargs)
    monkeypatch.setattr(app.state.market,'history',history)
    assert client.post('/api/strategies/backtest',headers=bob,json={'instrument_id':'nse_cm|1333'}).status_code==200
    assert seen==[2]


def test_live_algorithm_deployment_rejects_unsupported_execution(accounts):
    app,client,alice,bob=accounts
    response=client.post('/api/strategies/deploy',headers=bob,json={
        'instrument_id':'nse_cm|1333','mode':'live'})
    assert response.status_code==422
    assert client.get('/api/strategies/active',headers=bob).json()==[]


def test_invalid_websocket_token_never_falls_back_to_default_account(accounts):
    app,client,*_=accounts
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/ws/stream?token=invalid'):
            pass


def test_paper_reset_clears_price_source(accounts):
    app,client,alice,bob=accounts
    with app.state.store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('paper_source:2','kotak')")
    response=client.post('/api/paper/reset',headers=bob,json={'confirmation':'RESET PAPER ACCOUNT'})
    assert response.status_code==200 and response.json()['source']=='demo'
    assert response.json()['valuation_error'] is None


def test_development_private_api_requires_signin(tmp_path):
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='development',
                            app_password=None,kotak_consumer_key=None))
    with TestClient(app) as client:
        assert client.get('/api/paper').status_code==401
        assert client.get('/api/session').json()['authenticated'] is False


def test_paper_strategy_does_not_claim_to_run_without_a_market_feed(accounts):
    app,client,alice,bob=accounts
    response=client.post('/api/strategies/deploy',headers=bob,json={
        'instrument_id':'nse_cm|1333','mode':'paper'})
    assert response.status_code==200
    strategy=response.json()
    assert strategy['status']=='PAUSED'
    assert client.post(f"/api/strategies/{strategy['id']}/resume",headers=bob).status_code==503


def test_old_order_schema_migrates_without_losing_orders(tmp_path):
    import sqlite3
    from app.terminal.store import Store
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE orders (
            id TEXT PRIMARY KEY,user_id INTEGER DEFAULT 1,request_id TEXT UNIQUE,instrument_id TEXT,
            side TEXT,quantity INTEGER,order_type TEXT,limit_price INTEGER,fill_price INTEGER,
            status TEXT,created_at TEXT,filled_at TEXT,source TEXT,symbol TEXT)''')
        db.execute("INSERT INTO orders(id,user_id,request_id,status) VALUES ('old-order',1,'same-retry','FILLED')")
    store=Store(path,100000)
    with store.connect() as db:
        assert dict(db.execute("SELECT id,status FROM orders WHERE id='old-order'").fetchone())=={'id':'old-order','status':'FILLED'}
        db.execute("INSERT INTO orders(id,user_id,request_id) VALUES ('new-order',2,'same-retry')")
    assert Store(path,100000).orders(1)[0]['id']=='old-order'


def test_saved_strategy_can_be_stopped_after_restart(accounts):
    app,client,alice,bob=accounts
    saved=client.post('/api/strategies/deploy',headers=bob,json={'instrument_id':'nse_cm|1333'}).json()
    restarted=create_app(app.state.config)
    with TestClient(restarted,headers={'X-NeoDesk':'1'}) as another:
        assert another.delete('/api/strategies/'+saved['id'],headers=bob).status_code==200
        assert another.get('/api/strategies/'+saved['id'],headers=bob).json()['status']=='STOPPED'


def test_stop_orders_and_limits_survive_restart(accounts):
    app,client,alice,bob=accounts
    assert client.post('/api/risk/kill-switch',headers=bob).status_code==200
    assert client.put('/api/risk/limits',headers=bob,json={'max_order_value':1234}).status_code==200
    restarted=create_app(app.state.config)
    with TestClient(restarted) as another:
        status=another.get('/api/risk/status',headers=bob).json()
        assert status['kill_switch_active'] is True
        assert status['limits']['max_order_value']==1234
