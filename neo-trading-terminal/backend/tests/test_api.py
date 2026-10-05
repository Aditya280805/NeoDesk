from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.terminal.server import create_app
from app.terminal.store import Store
from app.terminal.paper import PaperAccount
from app.terminal.market import parse_master
from app.terminal.analytics import indicators, backtest


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,market_data_source='sample',kotak_consumer_key=None))


@pytest.fixture
def client(app):
    with TestClient(app,headers={'X-NeoDesk':'1'}) as client:
        yield client


def request(**kwargs):
    return {'instrument_id':'nse_cm|1333','side':'BUY','quantity':2,'order_type':'MARKET','request_id':str(uuid4()),**kwargs}


def test_health_and_paper_status(client):
    assert client.get('/api/health').json()['status']=='healthy'
    assert client.get('/api/status').json()['live_trading_enabled'] is False
    assert client.get('/api/paper').json()['cash']==100000


def test_market_fill_cash_holdings_and_restart(client,app):
    q=client.post('/api/market/quotes',json={'ids':['nse_cm|1333']}).json()[0]
    result=client.post('/api/paper/orders',json=request())
    assert result.status_code==201
    account=client.get('/api/paper').json()
    assert account['positions'][0]['quantity']==2
    assert account['cash']==pytest.approx(100000-2*q['ltp'])
    reopened=PaperAccount(Store(app.state.store.path,999999)).snapshot({q['id']:q})
    assert reopened['cash']==account['cash']
    assert reopened['initial']==100000


def test_idempotency_and_conflicting_request(client):
    body=request()
    first=client.post('/api/paper/orders',json=body).json()
    second=client.post('/api/paper/orders',json=body).json()
    assert first['id']==second['id']
    assert len(client.get('/api/paper').json()['orders'])==1
    assert client.post('/api/paper/orders',json={**body,'quantity':3}).status_code==422


def test_insufficient_funds_short_sell_index_and_invalid_float(client):
    for body in [request(quantity=10000),request(side='SELL'),request(instrument_id='nse_cm|26000'),request(order_type='LIMIT',limit_price=-1)]:
        assert client.post('/api/paper/orders',json=body).status_code==422


def test_limit_reservations_and_cancellation(client):
    result=client.post('/api/paper/orders',json=request(order_type='LIMIT',limit_price=1,quantity=20)).json()
    assert result['status']=='OPEN'
    account=client.get('/api/paper').json()
    assert account['reserved']==20 and account['available']==99980
    assert client.delete('/api/paper/orders/'+result['id']).status_code==200
    assert client.get('/api/paper').json()['reserved']==0
    assert client.delete('/api/paper/orders/'+result['id']).status_code==422


def test_accounting_weighted_cost_and_realized(app):
    paper=app.state.paper;i=app.state.store.instrument('nse_cm|1333')
    def trade(side,qty,price):return paper.submit(i,side,qty,'MARKET',None,str(uuid4()),{'ltp':price,'source':'demo'})
    trade('BUY',10,100);trade('BUY',10,200);trade('SELL',5,180)
    snap=paper.snapshot({i['id']:{'ltp':180,'source':'demo'}})
    assert snap['positions'][0]['average_price']==150
    assert snap['positions'][0]['pnl']==450
    assert snap['realized']==150
    assert snap['equity']==100600


def test_limit_matching_and_source_isolation(app):
    p=app.state.paper;i=app.state.store.instrument('nse_cm|1333')
    order=p.submit(i,'BUY',10,'LIMIT',100,str(uuid4()),{'ltp':110,'source':'demo'})
    p.match({i['id']:{'ltp':90,'source':'kotak'}})
    assert app.state.store.orders()[0]['status']=='OPEN'
    p.match({i['id']:{'ltp':90,'source':'demo'}})
    assert app.state.store.orders()[0]['status']=='FILLED'
    assert app.state.store.orders()[0]['fill_price']==9000
    with pytest.raises(ValueError,match='another data source'):
        p.submit(i,'BUY',1,'MARKET',None,str(uuid4()),{'ltp':90,'source':'kotak'})


def test_catalogue_search_and_direct_lookup(client):
    result=client.get('/api/instruments',params={'q':'HDFC','kind':'EQUITY'}).json()
    assert result['total']==1
    assert client.get('/api/instruments/nse_cm%7C1333').json()['symbol']=='HDFCBANK-EQ'


def test_master_parser_units():
    rows=parse_master('pSymbol,pTrdSymbol,pInstType,pGroup,pISIN,dTickSize ,lLotSize,dStrikePrice;\n1,X,OPTIDX,,,5,65,2500000\n','nse_fo')
    assert rows[0]['strike']==25000 and rows[0]['lot_size']==65 and rows[0]['tick_size']==.05


def test_bse_derivative_types():
    rows=parse_master('pSymbol,pTrdSymbol,pInstType\n1,SENSEXCE,IO\n2,STOCKPE,SO\n3,SENSEXFUT,IF\n4,STOCKFUT,SF\n','bse_fo')
    assert [r['kind'] for r in rows]==['OPTION','OPTION','FUTURE','FUTURE']


def test_actual_option_chain_shape(client,app,monkeypatch):
    raw={'common_data':{'unlSymbol':'NIFTY','expiryDt':'2026-10-06','mktLot':'65'},
         'call':[{'inst':{'neoSymbol':'nse_fo|1','symbol':'NIFTYCE','strkPrc':'25000'},
                  'quote':{'ltp':'125.5','vol':'200'},'oi':{'cur':'650'}}],'put':[]}
    monkeypatch.setattr(app.state.market,'call',lambda *args,**kwargs:raw)
    response=client.get('/api/market/chain')
    assert response.status_code==200
    leg=response.json()['call'][0]
    assert leg['instrument']['strikePrice']=='25000'
    assert leg['quote']=={'ltp':125.5,'volume':200}
    assert leg['openInterest']['current']==650


def test_history_inclusive_batches_and_daily_dates(app,monkeypatch):
    from datetime import date,datetime,UTC
    market=app.state.market
    market.source='kotak'
    calls=[]
    def historical(method,**kwargs):
        assert method=='historical_data'
        start,end=date.fromisoformat(kwargs['from_date']),date.fromisoformat(kwargs['to_date'])
        assert (end-start).days+1<=180
        calls.append((start,end))
        return {'data':{'candles':[[start.isoformat()+'T00:00:00+0530',100,110,90,105,500]]}}
    monkeypatch.setattr(market,'call',historical)
    result=market.history('nse_cm|1333','D',365)
    assert len(calls)==3
    assert sum((end-start).days+1 for start,end in calls)==365
    assert all((calls[i+1][0]-calls[i][1]).days==1 for i in range(2))
    assert datetime.fromtimestamp(result['candles'][0]['time'],UTC).date()==calls[0][0]
    assert market.history('nse_cm|1333','D',365)==result and len(calls)==3


def test_partial_history_visible_but_not_backtested(client,app,monkeypatch):
    from app.brokers.base_broker import BrokerError
    market=app.state.market
    market.source='kotak'
    calls=[]
    def historical(method,**kwargs):
        calls.append(kwargs)
        if len(calls)==1:
            raise BrokerError('Kotak market-data service is temporarily unavailable.')
        return {'data':{'candles':[[kwargs['from_date']+'T00:00:00+0530',100,110,90,105,500]]}}
    monkeypatch.setattr(market,'call',historical)
    response=client.get('/api/market/history',params={'instrument_id':'nse_cm|1333'})
    assert response.status_code==200
    assert response.json()['partial'] is True
    assert 'INCOMPLETE HISTORY' in response.json()['note']
    assert len(response.json()['candles'])==2
    assert client.post('/api/strategies/backtest',json={'instrument_id':'nse_cm|1333'}).status_code==503


def test_origin_and_redacted_validation(client):
    assert client.post('/api/connection',headers={'origin':'https://evil.example'},json={'consumer_key':'private'}).status_code==403
    result=client.post('/api/connection',json={'consumer_key':{'secret':'private-test-secret'}})
    assert result.status_code==422
    assert 'private-test-secret' not in result.text


def test_hosted_login_protects_account_and_connection(tmp_path):
    config=Settings(_env_file=None,data_dir=tmp_path,environment='production',app_password='a-long-private-password',kotak_consumer_key=None)
    app=create_app(config)
    with TestClient(app,base_url='https://testserver',headers={'X-NeoDesk':'1'}) as c:
        assert c.get('/api/paper').status_code==401
        assert c.post('/api/connection',json={'consumer_key':'x'}).status_code==401
        assert c.post('/api/login',json={'password':'wrong'}).status_code==401
        result=c.post('/api/login',json={'password':'a-long-private-password'})
        assert 'HttpOnly' in result.headers['set-cookie'] and 'Secure' in result.headers['set-cookie']
        assert c.get('/api/paper').status_code==200
        c.post('/api/logout')
        assert c.get('/api/paper').status_code==401


def test_production_requires_password(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(Settings(_env_file=None,data_dir=tmp_path,environment='production',app_password=None))


def test_reset_requires_explicit_confirmation(client):
    client.post('/api/paper/orders',json=request())
    assert client.post('/api/paper/reset',json={'confirmation':'yes'}).status_code==422
    assert client.post('/api/paper/reset',json={'confirmation':'RESET PAPER ACCOUNT'}).json()['cash']==100000


def test_rsi_warmup_and_no_lookahead():
    candles=[{'time':i,'open':100+i,'high':102+i,'low':99+i,'close':101+i,'volume':100} for i in range(100)]
    values=indicators(candles)
    assert values['rsi14'][13] is None and values['rsi14'][14]==100
    assert values['sma200'][-1] is None
    short=backtest(candles[:60],100000)
    extended=backtest(candles,100000)
    assert short['trades']==[t for t in extended['trades'] if t['time']<60]
    flat=indicators([dict(c,close=100) for c in candles])
    assert flat['rsi14'][-1]==50
