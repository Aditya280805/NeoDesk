
from fastapi import APIRouter, Request, HTTPException
from typing import Literal
from pydantic import BaseModel, Field
from app.auth.dependencies import get_request_user_id as get_user_id
from app.brokers.base_broker import BrokerError
import json
from app.terminal.analytics import indicators

market_router = APIRouter()

class QuoteRequest(BaseModel):
    ids: list[str] = Field(max_length=50)

@market_router.get('/api/instruments')
def instruments(request: Request, q: str='',exchange: str='',kind: str='',sort: Literal['name','name_desc','symbol','symbol_desc','exchange','kind']='symbol',offset: int=0,limit: int=40):
    return request.app.state.store.search(q[:100],exchange,kind,sort,max(0,offset),max(1,min(100,limit)))

@market_router.get('/api/watchlist')
def watchlist(request: Request):
    user_id = get_user_id(request)
    return request.app.state.store.watchlist(user_id)

@market_router.get('/api/stocks')
def stocks(request: Request, q: str='',exchange: str='',kind: str='EQUITY',sort: Literal['name','name_desc','symbol','symbol_desc','exchange','kind']='symbol',offset: int=0,limit: int=25):
    return request.app.state.store.search(q[:100],exchange,kind,sort,max(0,offset),max(1,min(limit,100)),scope='stocks')

@market_router.get('/api/indices')
def indices(request: Request, q: str=''):
    return request.app.state.discovery.indices(q[:100])

@market_router.get('/api/contracts')
def contracts(request: Request, underlying: str,exchange: Literal['nse_fo','bse_fo']='nse_fo',kind: Literal['OPTION','FUTURE']='OPTION',expiry: str='',option_type: str='',offset: int=0,limit: int=30,strike: float | None=None):
    return request.app.state.discovery.contracts(underlying[:50],exchange,kind,expiry,option_type,max(0,offset),max(1,min(limit,50)),strike)

@market_router.get('/api/market/activity')
def activity(request: Request, scope: Literal['stocks','indices']='stocks',metric: Literal['volume','turnover']='volume'):
    return request.app.state.discovery.activity(scope,metric,user_id=get_user_id(request))

@market_router.get('/api/instruments/{identifier}')
def instrument(request: Request, identifier: str):
    return request.app.state.store.instrument(identifier)

@market_router.get('/api/instrument-detail')
def instrument_detail(request: Request, instrument_id: str):
    user_id = get_user_id(request)
    store = request.app.state.store
    item=store.instrument(instrument_id)
    variants=[item]
    with store.connect() as db:
        if item['kind'] in ('EQUITY','ETF') and item.get('isin'):
            variants=[json.loads(r[0]) for r in db.execute("SELECT payload FROM instruments WHERE kind=? AND exchange IN ('nse_cm','bse_cm') AND json_extract(payload,'$.isin')=? ORDER BY exchange DESC",(item['kind'],item['isin']))]
        held=db.execute('SELECT quantity FROM positions WHERE user_id=? AND instrument_id=?',(user_id, instrument_id)).fetchone()
    return {'instrument':item,'variants':variants,'paper_quantity':held[0] if held else 0}

@market_router.post('/api/watchlist')
def watch(request: Request, body: QuoteRequest):
    user_id = get_user_id(request)
    for identifier in body.ids:
        request.app.state.store.watch(user_id, identifier)
    return request.app.state.store.watchlist(user_id)

@market_router.delete('/api/watchlist/{identifier}')
def unwatch(request: Request, identifier: str):
    user_id = get_user_id(request)
    request.app.state.store.watch(user_id, identifier, False)
    return request.app.state.store.watchlist(user_id)

@market_router.post('/api/market/quotes')
def quotes(request: Request, body: QuoteRequest):
    return request.app.state.market.quotes(body.ids,user_id=get_user_id(request))

@market_router.get('/api/market/quotes')
def watch_quotes(request: Request):
    user_id = get_user_id(request)
    return request.app.state.market.quotes([i['id'] for i in request.app.state.store.watchlist(user_id)],user_id=user_id)


@market_router.get('/api/market/history')
def history(request: Request, instrument_id: str,interval: Literal['1min','5min','15min','60min','D']='D',days: int=365):
    result=request.app.state.market.history(instrument_id,interval,max(1,days),user_id=get_user_id(request))
    return {**result,'indicators':indicators(result['candles'])}

@market_router.get('/api/market/expiries')
def expiries(request: Request, underlying: str='NIFTY',exchange: Literal['nse_fo','bse_fo']='nse_fo'):
    return request.app.state.market.call('expiries',user_id=get_user_id(request),exchange=exchange,underlying=underlying[:50],instrument_type='option')

@market_router.get('/api/market/chain')
def chain(request: Request, underlying: str='NIFTY',exchange: Literal['nse_fo','bse_fo']='nse_fo',expiry: str | None=None):
    raw=request.app.state.market.call('option_chain',user_id=get_user_id(request),exchange=exchange,underlying=underlying[:50],expiry=expiry,instrument_type='option',count=20)
    data=raw.get('data',raw) if isinstance(raw,dict) else None
    if not isinstance(data,dict) or not all(k in data for k in ('common_data','call','put')):
        raise BrokerError('Unexpected option-chain response.')
    try:
        def leg(row):
            instrument=row.get('instrument',row.get('inst'))
            quote=row['quote']
            oi=row.get('openInterest',row.get('oi',{}))
            return {'instrument':{'neoSymbol':instrument['neoSymbol'],'symbol':instrument['symbol'],
                    'strikePrice':str(instrument.get('strikePrice',instrument.get('strkPrc'))),
                    'moneyness':instrument.get('moneyness','')},
                    'quote':{'ltp':float(quote['ltp']),'volume':float(quote.get('volume',quote.get('vol',0)))},
                    'openInterest':{'current':float(oi.get('current',oi.get('cur',0)))}}
        return {'common_data':data['common_data'],'call':[leg(r) for r in data['call']],
                'put':[leg(r) for r in data['put']]}
    except (KeyError,TypeError,ValueError):
        raise BrokerError('Unexpected option-chain fields.') from None
