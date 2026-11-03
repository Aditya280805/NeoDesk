"""One-page login, portfolio isolation and manual orders without real broker traffic."""
import json
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.auth.router import _clear_rate_limits
from app.brokers.kotak_neo.kotak_broker import KotakNeoBroker
from app.core.config import Settings
from app.terminal.server import create_app


@pytest.fixture
def setup(tmp_path,monkeypatch):
    _clear_rate_limits()
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,
                            market_data_source='sample',kotak_consumer_key=None,live_trading_enabled=True))
    sdks={}
    def sdk(broker):
        ucc=broker.config.kotak_ucc
        if ucc not in sdks:
            client=MagicMock()
            def login(**kwargs):
                if kwargs['totp']=='000000': return {'error':'private-token-should-never-leak'}
                return {'data':{'status':'success','kType':'View','token':'private-view','sid':'private-sid'}}
            client.totp_login.side_effect=login
            client.totp_validate.return_value={'data':{'status':'success','kType':'Trade','token':'private-trade','sid':'private-sid'}}
            qty=2 if ucc=='ALICE' else 3
            client.holdings.return_value={'data':[{'displaySymbol':'HDFCBANK','quantity':qty,'averagePrice':100,
                'holdingCost':100*qty,'mktValue':120*qty,'sellableQuantity':qty,'exchangeSegment':'nse_cm',
                'exchangeIdentifier':'1333','instrumentToken':999,'accountNumber':'private-account'}]}
            client.positions.return_value={'data':[{'trdSym':'HDFCBANK-EQ','exSeg':'nse_cm','tok':'1333',
                'cfBuyQty':'0','flBuyQty':'2','cfSellQty':'0','flSellQty':'0','buyAmt':'200','sellAmt':'0','ltp':'120'}]}
            client.limits.return_value={'Net':'1000','MarginUsed':'50','RealizedMtomPrsnt':'10','accountId':'private-account'}
            client.order_report.return_value={'data':[]}
            client.place_order.return_value={'nOrdNo':f'{ucc}-order','stat':'Ok'}
            sdks[ucc]=client
        return sdks[ucc]
    monkeypatch.setattr(KotakNeoBroker,'_sdk',sdk)
    monkeypatch.setattr(app.state.market,'sync',lambda **kwargs:None)
    def quotes(ids,user_id=1):
        assert user_id>=2
        return [{'id':i,'ltp':120,'source':'kotak','symbol':'HDFCBANK-EQ','change_pct':0,'received_at':'2026-10-22T01:00:00Z'} for i in ids]
    monkeypatch.setattr(app.state.market,'quotes',quotes)
    return app,sdks


def login(client,ucc='ALICE',**overrides):
    return client.post('/api/auth/kotak-login',headers={'X-NeoDesk':'1'},json={
        'consumer_key':'private-consumer-key','ucc':ucc,'mobile':'+919876543210','totp':'123456','mpin':'654321',**overrides})


def test_signin_loads_holdings_cookie_and_preserves_identity(setup):
    app,sdks=setup
    with TestClient(app) as client:
        assert client.get('/api/live').status_code==401
        response=login(client)
        assert response.status_code==200
        uid=response.json()['user']['id']
        assert uid>=2
        cookie=response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert 'access_token' not in response.json()
        portfolio=client.get('/api/live').json()
        assert portfolio['holdings'][0]['instrument_id']=='nse_cm|1333'  # exchangeIdentifier, not instrumentToken
        assert portfolio['invested']==200 and portfolio['holdings_value']==240 and portfolio['holdings_pnl']==40
        assert portfolio['positions'][0]['quantity']==2 and portfolio['positions'][0]['pnl'] is None  # Missing scale and carry-forward amounts cannot imply zero/one.
        assert portfolio['equity'] is None  # Available funds are not total account equity.
        assert portfolio['available']==1000
        assert sdks['ALICE'].holdings.call_count==1  # Login warms the per-user cache.
        text=json.dumps(portfolio)
        assert 'private-' not in text
        assert client.get('/api/session').json()['user']['id']==uid
        client.post('/api/auth/logout',headers={'X-NeoDesk':'1'})
        assert client.get('/api/live').status_code==401
        assert not app.state.market.get_session(uid).broker.is_authenticated
        assert login(client).json()['user']['id']==uid
        with app.state.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM broker_identities').fetchone()[0]==1
            assert 'private-consumer-key' not in str([dict(r) for r in db.execute('SELECT * FROM users')])


def test_rejected_login_never_creates_identity_or_cookie(setup):
    app,sdks=setup
    with TestClient(app) as client:
        response=login(client,totp='000000')
        assert response.status_code==401
        assert 'private-' not in response.text
        assert 'neodesk_token' not in response.cookies
        with app.state.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM broker_identities').fetchone()[0]==0
        response=login(client,mpin='bad-secret')
        assert response.status_code==422 and 'bad-secret' not in response.text


def test_two_users_portfolios_and_orders_are_isolated(setup):
    app,sdks=setup
    with TestClient(app) as alice,TestClient(app) as bob:
        alice_id=login(alice).json()['user']['id']
        bob_id=login(bob,'BOB').json()['user']['id']
        assert alice_id!=bob_id
        assert alice.get('/api/live').json()['holdings_value']==240
        assert bob.get('/api/live').json()['holdings_value']==360
        req={'instrument_id':'nse_cm|1333','side':'BUY','quantity':1,'order_type':'MARKET','request_id':str(uuid4())}
        first=alice.post('/api/live/orders',headers={'X-NeoDesk':'1'},json=req)
        assert first.status_code==201 and first.json()=={'id':'ALICE-order','status':'SUBMITTED'}
        assert sdks['ALICE'].place_order.call_count==1 and sdks['BOB'].place_order.call_count==0
        assert sdks['ALICE'].place_order.call_args.kwargs['product']=='CNC'
        again=alice.post('/api/live/orders',headers={'X-NeoDesk':'1'},json=req)
        assert again.json()==first.json() and sdks['ALICE'].place_order.call_count==1
        changed=alice.post('/api/live/orders',headers={'X-NeoDesk':'1'},json={**req,'quantity':2})
        assert changed.status_code==409
        cancel=bob.delete('/api/live/orders/ALICE-order',headers={'X-NeoDesk':'1'})
        assert cancel.status_code==404 and sdks['BOB'].cancel_order.call_count==0


def test_timeout_retry_and_server_disable_never_duplicate_orders(setup):
    app,sdks=setup
    with TestClient(app) as client:
        login(client)
        req={'instrument_id':'nse_cm|1333','side':'BUY','quantity':1,'request_id':str(uuid4())}
        sdks['ALICE'].place_order.side_effect=TimeoutError('private transport data')
        res=client.post('/api/live/orders',headers={'X-NeoDesk':'1'},json=req)
        assert res.status_code==502 and 'private' not in res.text
        retry=client.post('/api/live/orders',headers={'X-NeoDesk':'1'},json=req)
        assert retry.status_code==409 and sdks['ALICE'].place_order.call_count==1
        app.state.config.live_trading_enabled=False
        blocked=client.post('/api/live/orders',headers={'X-NeoDesk':'1'},json={**req,'request_id':str(uuid4())})
        assert blocked.status_code==403 and sdks['ALICE'].place_order.call_count==1


def test_sync_failure_is_visible_but_does_not_fabricate_holdings(setup):
    app,sdks=setup
    with TestClient(app) as client:
        login(client)
        sdks['ALICE'].holdings.return_value={'Error':'private failure'}
        response=client.get('/api/live?refresh=true')
        assert response.status_code==200 and 'private failure' not in response.text
        assert 'holdings' in response.json()['section_errors']
        assert response.json()['holdings_value'] is None
        assert response.json()['available']==1000
        # Known broker expiry invalidates the session rather than showing an empty portfolio.
        sdks['ALICE'].holdings.return_value={'stCode':403,'stat':'Not_Ok'}
        assert client.get('/api/live?refresh=true').status_code==503
        assert not client.get('/api/status').json()['broker_authenticated']


def test_positions_failure_does_not_hide_holdings_or_funds(setup):
    app,sdks=setup
    with TestClient(app) as client:
        login(client)
        sdks['ALICE'].positions.return_value={'Error':'private upstream error'}
        result=client.get('/api/live?refresh=true')
        assert result.status_code==200
        data=result.json()
        assert data['holdings_value']==240 and data['available']==1000
        assert data['positions']==[] and 'positions' in data['section_errors']
        assert 'private upstream' not in result.text
        sdks['ALICE'].positions.return_value={'data':[]}
        data=client.get('/api/live?refresh=true').json()
        assert data['positions']==[] and data['section_errors']=={}


def test_malformed_orders_do_not_hide_holdings(setup):
    app,sdks=setup
    with TestClient(app) as client:
        login(client)
        sdks['ALICE'].order_report.return_value={'data':None}
        data=client.get('/api/live?refresh=true').json()
        assert data['holdings_value']==240 and 'orders' in data['section_errors']


@pytest.mark.anyio
async def test_socket_updates_are_delivered_only_to_the_owner():
    from unittest.mock import AsyncMock
    from app.websocket.manager import ConnectionManager
    manager=ConnectionManager()
    alice,bob=MagicMock(),MagicMock()
    for socket in (alice,bob):
        socket.accept=AsyncMock()
        socket.send_text=AsyncMock()
    await manager.connect(alice,user_id=2)
    await manager.connect(bob,user_id=3)
    await manager.broadcast({'type':'SIGNAL','data':{'price':120},'user_id':2})
    assert alice.send_text.call_count==1 and bob.send_text.call_count==0
    await manager.broadcast({'type':'QUOTE','data':{'id':'nse_cm|1333','ltp':120},'user_id':2})
    assert 2 in manager.last_quotes and 3 not in manager.last_quotes


def test_paper_price_sources_are_independent_per_user(setup):
    app,_=setup
    store,paper=app.state.store,app.state.paper
    for uid,source in ((2,'demo'),(3,'kotak')):
        store.init_user_account(uid,100000)
        item=store.instrument('nse_cm|1333')
        paper.submit(item,'BUY',1,'MARKET',None,str(uuid4()),{'source':source,'ltp':100},user_id=uid)
    with store.connect() as db:
        assert db.execute("SELECT value FROM metadata WHERE key='paper_source:2'").fetchone()[0]=='demo'
        assert db.execute("SELECT value FROM metadata WHERE key='paper_source:3'").fetchone()[0]=='kotak'
