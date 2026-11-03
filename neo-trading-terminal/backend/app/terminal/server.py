"""
Main FastAPI server module for NeoDesk Trading Terminal.

Wires together the Store, Market, PaperAccount, and StrategyEngine into a 
unified API. Manages background loops for quotes and order matching, handles 
REST endpoints, and serves the frontend application.
"""
import asyncio
import hashlib
import secrets
import time
import os
import json
from contextlib import asynccontextmanager
from threading import Lock

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
from app.terminal.portfolio_risk_store import PortfolioRiskStore
from app.terminal.paper import PaperAccount
from app.terminal.market import Market
from app.terminal.discovery import Discovery
from app.terminal.engine import StrategyEngine
from app.terminal.risk import RiskManager
from app.auth.service import decode_token
from app.auth.router import auth_router

class Credentials(BaseModel):
    consumer_key: SecretStr


class BrokerLogin(BaseModel):
    ucc: str = Field(min_length=1,max_length=30)
    mobile: str = Field(pattern=r'^\+[0-9]{10,15}$')
    totp: SecretStr
    mpin: SecretStr


class Password(BaseModel):
    password: SecretStr


def create_app(config: Settings):
    if config.environment == 'production' and (not config.app_password or len(config.app_password.get_secret_value())<16):
        raise RuntimeError('Set a private APP_PASSWORD of at least 16 characters before deploying.')
    store = Store(config.data_dir / 'terminal.sqlite3', config.paper_starting_balance)
    portfolio_risk_store = PortfolioRiskStore(store)
    market = Market(config,store)
    paper = PaperAccount(store)
    discovery = Discovery(store,market)
    risk_manager = RiskManager(store=store)
    # No strategy feed is attached by this server. Preserve saved strategies
    # without falsely reporting that they are evaluating or executing orders.
    for strategy in store.list_strategies(status='RUNNING'):
        store.update_strategy_state(strategy['id'],strategy['cash'],strategy['held'],status='PAUSED')
    strategy_engine = StrategyEngine(store, market, paper, risk_manager=risk_manager)
    sessions, attempts = {}, {}
    sync_lock = Lock()
    lifespan_lock = Lock()
    sync_status = {'running':False,'error':None}

    def quote_map(ids,user_id=1):
        result={}
        for start in range(0,len(ids),50):
            result.update({q['id']:q for q in market.quotes(ids[start:start+50],user_id=user_id)})
        return result

    async def match_loop():
        while True:
            await asyncio.sleep(5)
            with store.connect() as db:
                pending=[tuple(r) for r in db.execute("SELECT DISTINCT user_id,instrument_id FROM orders WHERE status='OPEN'")]
            for uid in {r[0] for r in pending}:
                ids=[r[1] for r in pending if r[0]==uid]
                try:
                    quotes=await run_in_threadpool(quote_map,ids,uid)
                    await run_in_threadpool(paper.match,quotes,uid)
                except (BrokerError,ValueError):
                    pass

    def recent_snapshots():
        with market.lock:
            return {(key[0],q['id']):q for key,(stamp, batch) in market.cache.items()
                    if time.monotonic()-stamp<10 for q in batch}

    async def sfeed_loop():
        # Forward validated REST snapshots to connected views. Quote requests are
        # driven by visible pages; this never implies an exchange tick subscription.
        while True:
            await asyncio.sleep(5)
            if not manager.active_connections:
                continue
            rows=await run_in_threadpool(recent_snapshots)
            for (uid,_),quote in rows.items():
                await manager.broadcast({'type':'QUOTE','data':quote,'user_id':uid})

    @asynccontextmanager
    async def owned_lifespan(app):
        from contextlib import AsyncExitStack
        from app.terminal.agent_logging import setup_agno_logging
        setup_agno_logging()
        async with AsyncExitStack() as stack:
            if config.options_agent_enabled:
                await stack.enter_async_context(app.state.options_agent.mcp.lifespan())
            await app.state.options_monitoring_service.start()
            await app.state.options_scanner_service.start()
            await app.state.options_backtest_service.start()
            task=asyncio.create_task(match_loop())
            sfeed_task=asyncio.create_task(sfeed_loop())
            try:
                yield
            finally:
                await app.state.options_backtest_service.stop()
                await app.state.options_scanner_service.stop()
                await app.state.options_monitoring_service.stop()
                task.cancel()
                sfeed_task.cancel()
                try:
                    await asyncio.gather(task,sfeed_task,return_exceptions=True)
                except asyncio.CancelledError:
                    pass
                market.broker.close()

    @asynccontextmanager
    async def lifespan(app):
        # Workers are shared by the app and their tasks belong to the event loop
        # that starts them. A nested client can use the app without owning shutdown.
        if not lifespan_lock.acquire(blocking=False):
            yield
            return
        try:
            async with owned_lifespan(app):
                yield
        finally:
            lifespan_lock.release()

    app=FastAPI(title='NeoDesk',version='0.3.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store,app.state.market,app.state.paper,app.state.risk_manager,app.state.discovery,app.state.strategy_engine=store,market,paper,risk_manager,discovery,strategy_engine
    app.state.jwt_secret = config.jwt_secret
    app.state.config = config
    from app.terminal.options_agent import OptionsAgent
    from app.terminal.portfolio_service import PortfolioSnapshotService
    app.state.portfolio_risk_store = portfolio_risk_store
    app.state.portfolio_service = PortfolioSnapshotService(market, store)
    app.state.options_agent = OptionsAgent(config, store, market, portfolio_service=app.state.portfolio_service, risk_store=portfolio_risk_store)
    from app.terminal.options_platform_store import OptionsPlatformStore
    from app.terminal.options_platform_service import OptionsPlatformService
    app.state.options_platform_store = OptionsPlatformStore(store)
    app.state.options_platform_service = OptionsPlatformService(app.state.options_agent, app.state.options_platform_store)
    from app.terminal.options_monitoring import OptionsMonitoringService
    app.state.options_monitoring_service = OptionsMonitoringService(app.state.options_platform_service)
    app.state.options_agent.monitoring_service = app.state.options_monitoring_service
    from app.terminal.options_scan_jobs import OptionsScannerService
    app.state.options_scanner_service = OptionsScannerService(app.state.options_platform_service)
    from app.terminal.options_backtest_jobs import BacktestService
    app.state.options_backtest_service = BacktestService(app.state.options_platform_store)
    app.state.catalogue_lock = sync_lock
    app.state.catalogue_sync = sync_status
    app.state.is_production = (config.environment == 'production')
    app.add_middleware(CORSMiddleware,allow_origins=[config.frontend_url],allow_credentials=True,
                       allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-NeoDesk','Authorization'])

    def authenticated(request: Request):
        # 1. Try JWT from Authorization header or neodesk_token cookie
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        elif 'neodesk_token' in request.cookies:
            token = request.cookies.get('neodesk_token')

        if token:
            try:
                payload = decode_token(token, config.jwt_secret)
                user = store.get_user_by_id(payload['user_id'])
                if user:
                    request.state.user = {
                        'id': user['id'],
                        'email': user['email'],
                        'display_name': user['display_name'],
                        'created_at': user['created_at'],
                    }
                    return True
                return False
            except Exception:
                return False

        # 2. Backward compatibility fallback: APP_PASSWORD flow
        if config.app_password:
            token = request.cookies.get('neodesk_session', '')
            return sessions.get(hashlib.sha256(token.encode()).hexdigest(), 0) > time.time()
        return config.environment == 'test' and request.client and request.client.host in ('127.0.0.1', '::1', 'testclient')

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/ws/stream'):
            norm_path = request.url.path.rstrip('/')
            public = norm_path in ('/api/health', '/api/auth/register', '/api/auth/login', '/api/auth/kotak-login', '/api/session', '/api/login')
            if request.method != 'OPTIONS' and not public and not authenticated(request):
                return JSONResponse({'detail': 'Sign in to your terminal.'}, status_code=401)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                origin = request.headers.get('origin')
                same = f'{request.url.scheme}://{request.url.netloc}'
                if request.headers.get('x-neodesk') != '1' or (origin and origin not in (config.frontend_url, same, os.getenv('RENDER_EXTERNAL_URL'))):
                    return JSONResponse({'detail': 'Request origin rejected.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.websocket('/api/ws/stream')
    async def websocket_endpoint(websocket: WebSocket):
        token = websocket.query_params.get('token') or websocket.cookies.get('neodesk_token')
        auth_ok = False
        user_id = 1
        if token:
            try:
                payload = decode_token(token, config.jwt_secret)
                if store.get_user_by_id(payload['user_id']):
                    auth_ok = True
                    user_id = payload['user_id']
            except Exception:
                pass
        if not token and config.app_password:
            legacy_token = websocket.cookies.get('neodesk_session', '')
            if sessions.get(hashlib.sha256(legacy_token.encode()).hexdigest(), 0) >= time.time():
                auth_ok = True
        elif not token and not config.app_password and config.environment == 'test':
            auth_ok = True

        if not auth_ok:
            await websocket.close(code=1008)
            return
        
        await manager.connect(websocket,user_id=user_id)
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
        return {'authenticated':bool(authenticated(request)), 'password_required':bool(config.app_password), 'user': getattr(request.state, 'user', None)}

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
        # Deprecated: use /api/auth/logout instead.
        sessions.pop(hashlib.sha256(request.cookies.get('neodesk_session','').encode()).hexdigest(),None)
        response.delete_cookie('neodesk_session')
        response.delete_cookie('neodesk_token')
        return {'ok':True}

    def get_req_user_id(request: Request | None) -> int:
        if not request:
            return 1
        user = getattr(request.state, 'user', None)
        return user['id'] if user else 1

    @app.get('/api/status')
    def status(request: Request = None):
        uid = get_req_user_id(request)
        sess = market.get_session(uid)
        return {'mode':'paper','live_trading_enabled':config.live_trading_enabled,'market_data_source':sess.source,
                'kotak_api_key_configured':bool(sess.config.kotak_consumer_key),
                'broker_authenticated':sess.broker.is_authenticated,'catalogue':store.metadata(),
                'catalogue_sync':sync_status,'paper_starting_balance':config.paper_starting_balance,
                'market_error':sess.last_error,'orders_stopped':risk_manager.for_user(uid).kill_switch_active}

    @app.post('/api/connection')
    def connect(body: Credentials, request: Request = None):
        uid = get_req_user_id(request)
        market.connect(body.consumer_key.get_secret_value(), user_id=uid)
        return status(request)

    @app.delete('/api/connection')
    def disconnect(request: Request = None):
        uid = get_req_user_id(request)
        market.disconnect(user_id=uid)
        return status(request)

    @app.post('/api/connection/login')
    def broker_login(body: BrokerLogin, request: Request = None):
        uid = get_req_user_id(request)
        is_auth = market.broker_login(body.ucc, body.mobile, body.totp.get_secret_value(), body.mpin.get_secret_value(), user_id=uid)
        return {'authenticated': is_auth}

    @app.get('/api/broker/account')
    def broker_account(request: Request = None):
        uid = get_req_user_id(request)
        sess = market.get_session(uid)
        if not sess.broker.is_authenticated:
            raise HTTPException(401,'Complete Kotak TOTP/MPIN login in Connections.')
        limits=market.call('limits', user_id=uid)
        positions=market.call('positions', user_id=uid)
        if not isinstance(limits,dict) or not isinstance(positions,dict):
            raise BrokerError('Unexpected account response; please reconnect.')
        records=positions.get('data',[])
        if not isinstance(records,list):
            raise BrokerError('Unexpected positions response.')
        # Allowlist display fields; session/account identifiers never leave the server.
        allowed=('trdSym','tradingSymbol','netQty','flBuyQty','flSellQty','buyAmt','sellAmt','cfBuyQty','cfSellQty','mtm','rpnl','urmtom','exSeg','prod')
        return {'funds':{k:limits.get(k) for k in ('Net','MarginUsed','CollateralValue','RealizedMtomPrsnt','UnrealizedMtomPrsnt')},
                'positions':[{k:r.get(k) for k in allowed if k in r} for r in records if isinstance(r,dict)]}


    async def do_sync(user_id=1):
        try:
            await run_in_threadpool(market.sync,user_id=user_id)
        except Exception:
            sync_status['error']='Catalogue sync failed. Check the broker connection and retry; previous catalogue retained.'
        finally:
            sync_status['running']=False
            sync_lock.release()

    @app.post('/api/instruments/sync',status_code=202)
    async def sync(request: Request = None):
        uid = get_req_user_id(request)
        sess = market.get_session(uid)
        if sess.source != 'kotak' and market.source != 'kotak':
            raise ValueError('Connect Kotak first.')
        if not sync_lock.acquire(blocking=False):
            raise HTTPException(409,'Catalogue sync is already running.')
        sync_status.update(running=True,error=None)
        asyncio.create_task(do_sync(uid))
        return {'running':True}

    
    from app.terminal.routers.market import market_router
    from app.terminal.routers.paper import paper_router
    from app.terminal.routers.strategy import strategy_router
    from app.terminal.routers.risk import risk_router
    
    app.include_router(market_router)
    app.include_router(paper_router)
    app.include_router(strategy_router)
    app.include_router(risk_router)

    from app.terminal.live import live_router
    app.include_router(live_router, prefix="/api")
    app.include_router(auth_router)
    from app.terminal.routers.options_agent import options_agent_router
    app.include_router(options_agent_router)
    from app.terminal.routers.options_platform import options_platform_router
    app.include_router(options_platform_router)

    static=PROJECT_ROOT / 'frontend' / 'out'
    if static.exists():
        app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    return app
