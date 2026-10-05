from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.terminal.server import create_app
from app.terminal.store import Store
from app.terminal.paper import PaperAccount
from app.terminal.catalogue import expiry_date, normalise
from app.terminal.discovery import Discovery


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,market_data_source='sample',kotak_consumer_key=None))


def contract(kind='FUTURE',**values):
    return {'id':'nse_fo|1','token':'1','exchange':'nse_fo','symbol':'NIFTY50JANFUT','name':'NIFTY',
            'underlying':'NIFTY','kind':kind,'lot_size':2,'tick_size':.05,'expiry':'2050-01-01',
            'option_type':'CE' if kind=='OPTION' else '', 'strike':25000,'isin':'',**values}


def test_expiry_conventions_and_legacy_bse():
    assert expiry_date('1483021800','nse_fo')=='2026-12-29'
    assert expiry_date('1798741799','bse_fo')=='2026-12-31'
    assert expiry_date('2026-12-31','bse_fo')=='2026-12-31'
    assert normalise(contract('OTHER',exchange='bse_fo',option_type='PE'))['kind']=='OPTION'


def test_discovery_scopes_and_active_contracts(app):
    items=[contract(),contract('OPTION',id='nse_fo|2',symbol='NIFTY50JAN25000CE'),
           contract('OPTION',id='nse_fo|3',expiry='2020-01-01'),
           contract('OPTION',id='nse_fo|4',underlying='BANKNIFTY',strike=26000)]
    app.state.store.save_catalogue(items,['nse_fo'])
    with TestClient(app) as c:
        stocks=c.get('/api/stocks').json()['items']
        assert all(i['kind']=='EQUITY' and i['exchange'].endswith('_cm') for i in stocks)
        assert c.get('/api/stocks',params={'kind':'FUTURE'}).json()['total']==0
        indices=c.get('/api/indices',params={'q':'Nifty 50'}).json()
        assert len(indices)==1 and indices[0]['options_count']==1 and indices[0]['futures_count']==1
        response=c.get('/api/contracts',params={'underlying':'NIFTY','kind':'OPTION','strike':25000}).json()
        assert [i['id'] for i in response['items']]==['nse_fo|2']
        assert response['expiry']=='2050-01-01'


def test_futures_long_partial_close_reverse_and_restart(app):
    i=contract();p=app.state.paper
    app.state.store.save_catalogue([i],['nse_fo'])
    def trade(side,qty,price):return p.submit(i,side,qty,'MARKET',None,str(uuid4()),{'ltp':price,'source':'demo'})
    trade('BUY',10,100)
    snap=p.snapshot({i['id']:{'ltp':110}})
    assert snap['cash']==100000 and snap['available']==99800
    assert snap['equity']==100100 and snap['futures_margin']==200
    trade('SELL',6,110)
    assert p.snapshot({})['realized']==60
    trade('SELL',6,120)
    reopened=PaperAccount(Store(app.state.store.path,100000))
    snap=reopened.snapshot({i['id']:{'ltp':115}})
    assert snap['positions'][0]['quantity']==-2
    assert snap['positions'][0]['pnl']==10
    assert snap['realized']==140 and snap['equity']==100150 and snap['available']==100092
    trade('BUY',2,115)
    assert not p.snapshot({})['positions'] and p.snapshot({})['cash']==100150


def test_futures_margin_blocks_cash_spend_and_overexposure(app):
    p=app.state.paper;i=contract()
    p.submit(i,'BUY',1000,'MARKET',None,str(uuid4()),{'ltp':400,'source':'demo'})
    assert p.snapshot({})['available']==20000
    stock=app.state.store.instrument('nse_cm|1333')
    with pytest.raises(ValueError,match='Insufficient'):
        p.submit(stock,'BUY',300,'MARKET',None,str(uuid4()),{'ltp':100,'source':'demo'})
    with pytest.raises(ValueError,match='margin'):
        p.submit(i,'BUY',1000,'MARKET',None,str(uuid4()),{'ltp':400,'source':'demo'})


def test_future_idempotency_expiry_and_source(app):
    p=app.state.paper;i=contract();key=str(uuid4());q={'ltp':100,'source':'demo'}
    first=p.submit(i,'SELL',2,'MARKET',None,key,q)
    assert p.submit(i,'SELL',2,'MARKET',None,key,q)['id']==first['id']
    assert len(app.state.store.orders())==1
    with pytest.raises(ValueError,match='different order'):
        p.submit(i,'BUY',2,'MARKET',None,key,q)
    with pytest.raises(ValueError,match='another data source'):
        p.submit(i,'BUY',2,'MARKET',None,str(uuid4()),{'ltp':100,'source':'kotak'})
    with pytest.raises(ValueError,match='expired'):
        p.submit(contract(expiry='2020-01-01'),'BUY',2,'MARKET',None,str(uuid4()),q)
    with pytest.raises(ValueError,match='market orders only'):
        p.submit(i,'BUY',2,'LIMIT',100,str(uuid4()),q)


def test_activity_ranking_is_scoped_and_demo_unranked(app,monkeypatch):
    d=Discovery(app.state.store,app.state.market)
    assert d.activity('stocks','volume')['items']==[]
    app.state.market.source='kotak'
    monkeypatch.setattr(app.state.market,'quotes',lambda ids:[{'id':i,'volume':n+1,'turnover_estimate':100-n,'source':'kotak'} for n,i in enumerate(ids)])
    result=d.activity('stocks','volume')
    assert result['items'][0]['quote']['volume']==max(i['quote']['volume'] for i in result['items'])
    assert result['tracked']<50 and 'Selected NSE' in result['universe']


def test_catalogue_refresh_keeps_held_contract_metadata(app):
    i=contract();app.state.store.save_catalogue([i],['nse_fo'])
    app.state.paper.submit(i,'BUY',2,'MARKET',None,str(uuid4()),{'ltp':100,'source':'demo'})
    app.state.store.save_catalogue([],['nse_fo'])
    assert app.state.store.instrument(i['id'])['symbol']==i['symbol']
