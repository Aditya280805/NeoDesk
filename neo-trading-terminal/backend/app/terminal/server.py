import asyncio
import hashlib
import secrets
import time
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool
from app.websocket.manager import manager


from app.brokers.base_broker import BrokerError
from app.core.config import PROJECT_ROOT, Settings
from app.terminal.store import Store
from app.terminal.paper import PaperAccount
from app.terminal.market import Market
from app.terminal.analytics import indicators, backtest
from app.terminal.discovery import Discovery


class Credentials(BaseModel):
    consumer_key: SecretStr


class BrokerLogin(BaseModel):
    ucc: str = Field(min_length=1,max_length=30)
    mobile: str = Field(pattern=r'^\+[0-9]{10,15}$')
    totp: SecretStr
    mpin: SecretStr


class Password(BaseModel):
    password: SecretStr


class QuoteRequest(BaseModel):
    ids: list[str] = Field(max_length=50)


class PaperOrder(BaseModel):
    instrument_id: str = Field(max_length=100)
    side: Literal['BUY','SELL']
    quantity: int = Field(strict=True,gt=0,le=10000)
    order_type: Literal['MARKET','LIMIT'] = 'MARKET'
    limit_price: float | None = Field(default=None,gt=0,allow_inf_nan=False)
    request_id: UUID


class BacktestRequest(BaseModel):
    instrument_id: str
    fast: int = Field(default=20,ge=2,le=100)
    slow: int = Field(default=50,ge=3,le=200)
    initial: float = Field(default=100000,ge=100,le=10000000,allow_inf_nan=False)
    fee_bps: float = Field(default=5,ge=0,le=100,allow_inf_nan=False)
    slippage_bps: float = Field(default=5,ge=0,le=100,allow_inf_nan=False)


def create_app(config: Settings):
    if config.environment == 'production' and (not config.app_password or len(config.app_password.get_secret_value())<16):
        raise RuntimeError('Set a private APP_PASSWORD of at least 16 characters before deploying.')
    store = Store(config.data_dir / 'terminal.sqlite3', config.paper_starting_balance)
    market = Market(config,store)
    paper = PaperAccount(store)
    discovery = Discovery(store,market)
    sessions, attempts = {}, {}
    sync_lock = Lock()
    sync_status = {'running':False,'error':None}

    def quote_map(ids):
        result={}
        for start in range(0,len(ids),50):
            result.update({q['id']:q for q in market.quotes(ids[start:start+50])})
        return result

    async def match_loop():
        while True:
            await asyncio.sleep(5)
            with store.connect() as db:
                ids=[r[0] for r in db.execute("SELECT DISTINCT instrument_id FROM orders WHERE status='OPEN'")]
            if ids:
                try:
                    quotes=await run_in_threadpool(quote_map,ids)
                    await run_in_threadpool(paper.match,quotes)
                except (BrokerError,ValueError):
                    pass

    async def sfeed_loop():
        while True:
            await asyncio.sleep(2)
            if market.broker.is_authenticated:
                try:
                    from neo_api_client.websocket.feed import SFeedScrip, WsToken
                    async with market.broker.client.create_websocket() as ws:
                        last_sub = 0
                        while market.broker.is_authenticated:
                            if time.time() - last_sub > 10:
                                with store.connect() as db:
                                    watched = db.execute("SELECT exchange, instrument_token FROM instruments WHERE id IN (SELECT instrument_id FROM watchlist)").fetchall()
                                if watched:
                                    tokens = [WsToken(ex, tok) for ex, tok in watched]
                                    await ws.subscribe_scrips(tokens)
                                last_sub = time.time()
                            
                            try:
                                message = await asyncio.wait_for(ws.__anext__(), timeout=2.0)
                                if isinstance(message, SFeedScrip):
                                    await manager.broadcast({
                                        "type": "QUOTE",
                                        "data": {
                                            "token": message.instrument_token,
                                            "ltp": float(message.last_traded_price)
                                        }
                                    })
                            except asyncio.TimeoutError:
                                pass
                except Exception:
                    pass

    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(match_loop())
        sfeed_task=asyncio.create_task(sfeed_loop())
        yield
        task.cancel()
        sfeed_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        market.broker.close()

    app=FastAPI(title='NeoDesk',version='0.3.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store,app.state.market,app.state.paper=store,market,paper
    app.add_middleware(CORSMiddleware,allow_origins=[config.frontend_url],allow_credentials=True,
                       allow_methods=['GET','POST','DELETE'],allow_headers=['Content-Type','X-NeoDesk'])

    def authenticated(request):
        if not config.app_password:
            return config.environment != 'production' and request.client and request.client.host in ('127.0.0.1','::1','testclient')
        token=request.cookies.get('neodesk_session','')
        return sessions.get(hashlib.sha256(token.encode()).hexdigest(),0)>time.time()

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/ws/stream'):
            public=request.url.path in ('/api/health','/api/session','/api/login')
            if request.method != 'OPTIONS' and not public and not authenticated(request):
                return JSONResponse({'detail':'Sign in to your terminal.'},status_code=401)
            if request.method not in ('GET','HEAD','OPTIONS'):
                origin=request.headers.get('origin')
                same=f'{request.url.scheme}://{request.url.netloc}'
                if request.headers.get('x-neodesk')!='1' or (origin and origin not in (config.frontend_url,same,os.getenv('RENDER_EXTERNAL_URL'))):
                    return JSONResponse({'detail':'Request origin rejected.'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.websocket('/api/ws/stream')
    async def websocket_endpoint(websocket: WebSocket):
        if config.app_password:
            token = websocket.cookies.get('neodesk_session', '')
            if sessions.get(hashlib.sha256(token.encode()).hexdigest(), 0) < time.time():
                await websocket.close(code=1008)
                return
        
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        # Never echo submitted values, especially tokens, MPIN or TOTP.
        return JSONResponse({'detail':'Invalid request fields. Check the values and try again.'},status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=422)

    @app.exception_handler(BrokerError)
    async def broker_error(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=503)

    @app.get('/api/health')
    def health():
        return {'status':'healthy','version':'0.3.0'}

    @app.get('/api/session')
    def session(request: Request):
        return {'authenticated':bool(authenticated(request)), 'password_required':bool(config.app_password)}

    @app.post('/api/login')
    def login(body: Password,request: Request,response: Response):
        address=request.client.host
        recent=[t for t in attempts.get(address,[]) if time.time()-t<60]
        if len(recent)>=5:
            raise HTTPException(429,'Wait a minute before trying again.')
        attempts[address]=recent+[time.time()]
        if not config.app_password or not secrets.compare_digest(body.password.get_secret_value(),config.app_password.get_secret_value()):
            raise HTTPException(401,'Incorrect terminal password.')
        token=secrets.token_urlsafe(32)
        sessions.update({hashlib.sha256(token.encode()).hexdigest():time.time()+8*3600})
        for key,expiry in list(sessions.items()):
            if expiry<time.time():
                del sessions[key]
        response.set_cookie('neodesk_session',token,httponly=True,samesite='strict',secure=config.environment=='production',max_age=8*3600)
        return {'authenticated':True}

    @app.post('/api/logout')
    def logout(request: Request,response: Response):
        sessions.pop(hashlib.sha256(request.cookies.get('neodesk_session','').encode()).hexdigest(),None)
        response.delete_cookie('neodesk_session')
        return {'ok':True}

    @app.get('/api/status')
    def status():
        return {'mode':'paper','live_trading_enabled':False,'market_data_source':market.source,
                'kotak_api_key_configured':bool(market.config.kotak_consumer_key),
                'broker_authenticated':market.broker.is_authenticated,'catalogue':store.metadata(),
                'catalogue_sync':sync_status,'paper_starting_balance':config.paper_starting_balance,
                'market_error':market.last_error}

    @app.post('/api/connection')
    def connect(body: Credentials):
        market.connect(body.consumer_key.get_secret_value())
        return status()

    @app.delete('/api/connection')
    def disconnect():
        market.disconnect()
        return status()

    @app.post('/api/connection/login')
    def broker_login(body: BrokerLogin):
        with market.lock:
            if market.source!='kotak':
                raise ValueError('Connect the consumer key first.')
            market.config.kotak_ucc=body.ucc
            market.config.kotak_mobile_number=body.mobile
            market.broker.login(body.totp.get_secret_value(),body.mpin.get_secret_value())
        return {'authenticated':market.broker.is_authenticated}

    @app.get('/api/broker/account')
    def broker_account():
        if not market.broker.is_authenticated:
            raise HTTPException(401,'Complete Kotak TOTP/MPIN login in Connections.')
        limits=market.call('limits')
        positions=market.call('positions')
        if not isinstance(limits,dict) or not isinstance(positions,dict):
            raise BrokerError('Unexpected account response; please reconnect.')
        records=positions.get('data',[])
        if not isinstance(records,list):
            raise BrokerError('Unexpected positions response.')
        # Allowlist display fields; session/account identifiers never leave the server.
        allowed=('trdSym','tradingSymbol','netQty','flBuyQty','flSellQty','buyAmt','sellAmt','cfBuyQty','cfSellQty','mtm','rpnl','urmtom','exSeg','prod')
        return {'funds':{k:limits.get(k) for k in ('Net','MarginUsed','CollateralValue','RealizedMtomPrsnt','UnrealizedMtomPrsnt')},
                'positions':[{k:r.get(k) for k in allowed if k in r} for r in records if isinstance(r,dict)]}

    async def do_sync():
        try:
            await run_in_threadpool(market.sync)
        except Exception:
            sync_status['error']='Catalogue sync failed. Check the broker connection and retry; previous catalogue retained.'
        finally:
            sync_status['running']=False
            sync_lock.release()

    @app.post('/api/instruments/sync',status_code=202)
    async def sync():
        if market.source!='kotak':
            raise ValueError('Connect Kotak first.')
        if not sync_lock.acquire(blocking=False):
            raise HTTPException(409,'Catalogue sync is already running.')
        sync_status.update(running=True,error=None)
        asyncio.create_task(do_sync())
        return {'running':True}

    @app.get('/api/instruments')
    def instruments(q: str='',exchange: str='',kind: str='',sort: Literal['symbol','symbol_desc','exchange','kind']='symbol',offset: int=0,limit: int=40):
        return store.search(q[:100],exchange,kind,sort,max(0,offset),max(1,min(100,limit)))

    @app.get('/api/watchlist')
    def watchlist():
        return store.watchlist()

    @app.get('/api/stocks')
    def stocks(q: str='',exchange: str='',kind: str='EQUITY',sort: Literal['symbol','symbol_desc','exchange','kind']='symbol',offset: int=0,limit: int=25):
        return store.search(q[:100],exchange,kind,sort,max(0,offset),max(1,min(limit,100)),scope='stocks')

    @app.get('/api/indices')
    def indices(q: str=''):
        return discovery.indices(q[:100])

    @app.get('/api/contracts')
    def contracts(underlying: str,exchange: Literal['nse_fo','bse_fo']='nse_fo',kind: Literal['OPTION','FUTURE']='OPTION',expiry: str='',option_type: str='',offset: int=0,limit: int=30,strike: float | None=None):
        return discovery.contracts(underlying[:50],exchange,kind,expiry,option_type,max(0,offset),max(1,min(limit,50)),strike)

    @app.get('/api/market/activity')
    def activity(scope: Literal['stocks','indices']='stocks',metric: Literal['volume','turnover']='volume'):
        return discovery.activity(scope,metric)

    @app.get('/api/instruments/{identifier}')
    def instrument(identifier: str):
        return store.instrument(identifier)

    @app.post('/api/watchlist')
    def watch(body: QuoteRequest):
        for identifier in body.ids:
            store.watch(identifier)
        return store.watchlist()

    @app.delete('/api/watchlist/{identifier}')
    def unwatch(identifier: str):
        store.watch(identifier,False)
        return store.watchlist()

    @app.post('/api/market/quotes')
    def quotes(body: QuoteRequest):
        return market.quotes(body.ids)

    @app.get('/api/market/quotes')
    def watch_quotes():
        return market.quotes([i['id'] for i in store.watchlist()])

    @app.get('/api/market/history')
    def history(instrument_id: str,interval: Literal['1min','5min','15min','60min','D']='D',days: int=365):
        result=market.history(instrument_id,interval,max(1,days))
        return {**result,'indicators':indicators(result['candles'])}

    @app.get('/api/market/expiries')
    def expiries(underlying: str='NIFTY',exchange: Literal['nse_fo','bse_fo']='nse_fo'):
        return market.call('expiries',exchange=exchange,underlying=underlying[:50],instrument_type='option')

    @app.get('/api/market/chain')
    def chain(underlying: str='NIFTY',exchange: Literal['nse_fo','bse_fo']='nse_fo',expiry: str | None=None):
        raw=market.call('option_chain',exchange=exchange,underlying=underlying[:50],expiry=expiry,instrument_type='option',count=20)
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

    @app.get('/api/paper')
    def account():
        with store.connect() as db:
            ids=[r[0] for r in db.execute('SELECT instrument_id FROM positions WHERE quantity>0 UNION SELECT instrument_id FROM futures_positions WHERE quantity<>0')]
            source=db.execute("SELECT value FROM metadata WHERE key='paper_source'").fetchone()
        quotes={}
        error=None
        if source and source[0]!=market.source:
            error='Connect the original data source to value these holdings. Reset the account to change sources.'
        else:
            try:
                quotes=quote_map(ids)
            except (BrokerError,ValueError):
                error='Valuation unavailable; cash and holdings are retained.'
        return {**paper.snapshot(quotes),'source':source[0] if source else market.source,'valuation_error':error}

    @app.post('/api/paper/orders',status_code=201)
    def order(body: PaperOrder):
        instrument=store.instrument(body.instrument_id)
        if body.order_type=='LIMIT' and body.limit_price is None:
            raise ValueError('A limit order needs a limit price.')
        rows=market.quotes([body.instrument_id])
        if not rows:
            raise BrokerError('No usable price is available for this instrument. Order was not submitted.')
        quote=rows[0]
        return paper.submit(instrument,body.side,body.quantity,body.order_type,body.limit_price,str(body.request_id),quote)

    @app.delete('/api/paper/orders/{identifier}')
    def cancel(identifier: str):
        paper.cancel(identifier)
        return {'ok':True}

    @app.post('/api/paper/reset')
    def reset(body: dict):
        if body.get('confirmation')!='RESET PAPER ACCOUNT':
            raise ValueError('Type RESET PAPER ACCOUNT to confirm.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM positions')
            db.execute('DELETE FROM futures_positions')
            db.execute('DELETE FROM orders')
            db.execute('UPDATE account SET cash=initial,realized=0 WHERE id=1')
            db.execute("DELETE FROM metadata WHERE key='paper_source'")
        store.audit('paper_reset','User confirmed paper account reset.')
        return account()

    @app.post('/api/strategies/backtest')
    def strategy(body: BacktestRequest):
        instrument=store.instrument(body.instrument_id)
        if instrument['kind'] not in ('EQUITY','ETF','INDEX'):
            raise ValueError('This strategy tester supports stocks, ETFs and index studies only.')
        data=market.history(body.instrument_id,'D',365)
        if data.get('partial'):
            raise BrokerError('Backtest blocked: historical data is incomplete. Try again when Kotak history is available.')
        return {**backtest(data['candles'],body.initial,body.fast,body.slow,body.fee_bps,body.slippage_bps),
                'source':data['source'],'instrument':instrument['symbol'],'note':data['note']}

    static=PROJECT_ROOT / 'frontend' / 'out'
    if static.exists():
        app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    return app
