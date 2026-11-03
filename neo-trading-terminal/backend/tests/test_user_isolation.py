import pytest
from starlette.testclient import TestClient
from app.core.config import Settings
from app.terminal.server import create_app
from app.auth.router import _clear_rate_limits

def make_app(tmp_path):
    _clear_rate_limits()
    config = Settings(
        data_dir=tmp_path,
        app_password=None,
        environment='development',
        frontend_url='http://localhost:3000',
        paper_starting_balance=100000,
        market_data_source='sample',
        kotak_consumer_key=None,
    )
    return create_app(config)

def test_user_data_isolation(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)

    # 1. Register User A and User B
    res_a = client.post('/api/auth/register', json={
        'email': 'alice@example.com',
        'password': 'password123',
        'display_name': 'Alice'
    }, headers={'X-NeoDesk': '1'})
    assert res_a.status_code == 200
    token_a = res_a.json()['access_token']
    headers_a = {'Authorization': f'Bearer {token_a}', 'X-NeoDesk': '1'}

    res_b = client.post('/api/auth/register', json={
        'email': 'bob@example.com',
        'password': 'password123',
        'display_name': 'Bob'
    }, headers={'X-NeoDesk': '1'})
    assert res_b.status_code == 200

    token_b = res_b.json()['access_token']
    headers_b = {'Authorization': f'Bearer {token_b}', 'X-NeoDesk': '1'}

    # 2. Watchlist isolation
    # Alice (user 1) has initial seed items, Bob (user 2) has an empty watchlist
    bob_initial = client.get('/api/watchlist', headers=headers_b).json()
    assert len(bob_initial) == 0

    # Bob adds an instrument to his watchlist
    client.post('/api/watchlist', json={'ids': ['nse_cm|3045']}, headers=headers_b)
    bob_watch = client.get('/api/watchlist', headers=headers_b).json()
    alice_watch = client.get('/api/watchlist', headers=headers_a).json()

    assert len(bob_watch) == 1
    assert bob_watch[0]['id'] == 'nse_cm|3045'
    # Alice's watchlist does not contain Bob's added instrument
    assert not any(i['id'] == 'nse_cm|3045' for i in alice_watch)

    # Bob removes the instrument
    client.delete('/api/watchlist/nse_cm%7C3045', headers=headers_b)
    assert len(client.get('/api/watchlist', headers=headers_b).json()) == 0


    # 3. Paper account & order isolation
    alice_account = client.get('/api/paper', headers=headers_a).json()
    bob_account = client.get('/api/paper', headers=headers_b).json()
    assert alice_account['cash'] == 100000
    assert bob_account['cash'] == 100000
    assert len(alice_account['orders']) == 0
    assert len(bob_account['orders']) == 0

    # Alice places a buy order
    import uuid
    req_id = str(uuid.uuid4())
    order_res = client.post('/api/paper/orders', json={
        'instrument_id': 'nse_cm|1333',
        'side': 'BUY',
        'quantity': 1,
        'order_type': 'MARKET',
        'request_id': req_id
    }, headers=headers_a)
    assert order_res.status_code == 201

    # Alice has 1 order and positions, Bob has 0
    alice_post = client.get('/api/paper', headers=headers_a).json()
    bob_post = client.get('/api/paper', headers=headers_b).json()
    assert len(alice_post['orders']) == 1
    assert len(alice_post['positions']) == 1
    assert alice_post['cash'] < 100000
    assert len(bob_post['orders']) == 0
    assert len(bob_post['positions']) == 0
    assert bob_post['cash'] == 100000

    # Bob cannot cancel Alice's order
    alice_order_id = alice_post['orders'][0]['id']
    cancel_res = client.delete(f'/api/paper/orders/{alice_order_id}', headers=headers_b)
    assert cancel_res.status_code == 422 # Cannot cancel order not belonging to user or already filled

    # 4. Strategy isolation
    deploy_res = client.post('/api/strategies/deploy', json={
        'instrument_id': 'nse_cm|1333',
        'strategy_type': 'SMA_CROSSOVER',
        'fast': 10,
        'slow': 20,
        'initial': 50000,
        'name': "Alice's SMA"
    }, headers=headers_a)
    assert deploy_res.status_code == 200
    strat_id = deploy_res.json()['id']

    alice_strats = client.get('/api/strategies/active', headers=headers_a).json()
    bob_strats = client.get('/api/strategies/active', headers=headers_b).json()
    assert len(alice_strats) == 1
    assert alice_strats[0]['id'] == strat_id
    assert len(bob_strats) == 0

    # Bob cannot view Alice's strategy
    assert client.get(f'/api/strategies/{strat_id}', headers=headers_b).status_code == 404
    # Bob cannot stop Alice's strategy
    assert client.delete(f'/api/strategies/{strat_id}', headers=headers_b).status_code in (403, 404)


def test_kotak_session_isolation(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)

    # Register Alice and Bob
    res_a = client.post('/api/auth/register', json={
        'email': 'alice_kotak@example.com',
        'password': 'password123',
        'display_name': 'Alice'
    }, headers={'X-NeoDesk': '1'})
    token_a = res_a.json()['access_token']
    headers_a = {'Authorization': f'Bearer {token_a}', 'X-NeoDesk': '1'}

    res_b = client.post('/api/auth/register', json={
        'email': 'bob_kotak@example.com',
        'password': 'password123',
        'display_name': 'Bob'
    }, headers={'X-NeoDesk': '1'})
    token_b = res_b.json()['access_token']
    headers_b = {'Authorization': f'Bearer {token_b}', 'X-NeoDesk': '1'}

    # Both start with demo data
    status_a = client.get('/api/status', headers=headers_a).json()
    status_b = client.get('/api/status', headers=headers_b).json()
    assert status_a['market_data_source'] == 'demo'
    assert status_b['market_data_source'] == 'demo'
    assert status_a['kotak_api_key_configured'] is False
    assert status_b['kotak_api_key_configured'] is False

    # Connect Kotak for Alice by patching quotes verification
    from unittest.mock import patch
    with patch.object(app.state.market, 'quotes', return_value=[{'id': 'nse_cm|1333', 'ltp': 2500.0, 'source': 'kotak'}]):
        conn_res = client.post('/api/connection', json={'consumer_key': 'alice_dummy_key_valid'}, headers=headers_a)
        assert conn_res.status_code == 200
        assert conn_res.json()['market_data_source'] == 'kotak'
        assert conn_res.json()['kotak_api_key_configured'] is True

    # Alice now sees Kotak data source, Bob still sees Demo!
    status_a = client.get('/api/status', headers=headers_a).json()
    status_b = client.get('/api/status', headers=headers_b).json()
    assert status_a['market_data_source'] == 'kotak'
    assert status_a['kotak_api_key_configured'] is True
    assert status_b['market_data_source'] == 'demo'
    assert status_b['kotak_api_key_configured'] is False

    # Alice disconnects
    disc_res = client.delete('/api/connection', headers=headers_a)
    assert disc_res.status_code == 200
    assert disc_res.json()['market_data_source'] == 'demo'
    assert disc_res.json()['kotak_api_key_configured'] is False


def test_live_order_execution_safeguards(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)

    res_a = client.post('/api/auth/register', json={
        'email': 'trader_guard@example.com',
        'password': 'password123',
        'display_name': 'Trader Guard'
    }, headers={'X-NeoDesk': '1'})
    token_a = res_a.json()['access_token']
    headers_a = {'Authorization': f'Bearer {token_a}', 'X-NeoDesk': '1'}

    # Placing live order when broker is not authenticated must return 401
    import uuid
    res = client.post('/api/live/orders', json={
        'instrument_id': 'nse_cm|1333',
        'side': 'BUY',
        'quantity': 1,
        'order_type': 'MARKET',
        'request_id': str(uuid.uuid4())
    }, headers=headers_a)
    assert res.status_code == 401

    # Live account overview without Kotak TOTP/MPIN returns 401
    res_acct = client.get('/api/live', headers=headers_a)
    assert res_acct.status_code == 401

