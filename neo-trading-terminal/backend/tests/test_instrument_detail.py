from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.terminal.server import create_app

def make_app(tmp_path):
    return create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,kotak_consumer_key=None))

def test_index_quote_uses_broker_name_and_preserves_catalogue_id(tmp_path):
    app=make_app(tmp_path)
    market=app.state.market
    market.source='kotak'
    def quotes(strict):
        assert market.broker.config.kotak_instruments[0].instrument_token=='Nifty 50'
        return [{'exchange_segment':'nse_cm','instrument_token':'Nifty 50','ltp':23000,'change_pct':1,'source':'kotak'}]
    market.broker.get_quotes=MagicMock(side_effect=quotes)
    result=market.quotes(['nse_cm|26000'])
    assert result[0]['id']=='nse_cm|26000'
    assert result[0]['ltp']==23000

def test_detail_groups_only_same_isin_and_retains_holdings(tmp_path):
    app=make_app(tmp_path)
    item=app.state.store.instrument('nse_cm|1333')
    app.state.store.save_catalogue([item|{'isin':'INE123'},item|{'id':'bse_cm|500','exchange':'bse_cm','token':'500','isin':'INE123'},item|{'id':'bse_cm|501','exchange':'bse_cm','token':'501','isin':'OTHER'}],['nse_cm','bse_cm'])
    with app.state.store.connect() as db:
        db.execute('INSERT INTO positions VALUES (?,?,?)',(item['id'],10,10000))
    client=TestClient(app)
    r=client.get('/api/instrument-detail',params={'instrument_id':item['id']})
    assert r.status_code==200
    assert {v['id'] for v in r.json()['variants']}=={item['id'],'bse_cm|500'}
    assert r.json()['paper_quantity']==10
    assert client.get('/api/instrument-detail',params={'instrument_id':'missing'}).status_code==422

def test_index_history_uses_broker_identifier(tmp_path):
    app=make_app(tmp_path)
    market=app.state.market;market.source='kotak'
    market.call=MagicMock(return_value={'data':{'candles':[]}})
    market.history('nse_cm|26000','5min',1)
    assert market.call.call_args.kwargs['neosymbol']=='nse_cm|Nifty 50'
