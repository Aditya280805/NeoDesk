
from fastapi import APIRouter, Request, HTTPException
from typing import Literal, Any
from pydantic import BaseModel, Field
from app.auth.dependencies import get_request_user_id as get_user_id
from app.brokers.base_broker import BrokerError
from app.terminal.analytics import backtest

strategy_router = APIRouter()

class BacktestRequest(BaseModel):
    instrument_id: str
    fast: int = Field(default=20,ge=2,le=100)
    slow: int = Field(default=50,ge=3,le=200)
    initial: float = Field(default=100000,ge=100,le=10000000,allow_inf_nan=False)
    fee_bps: float = Field(default=5,ge=0,le=100,allow_inf_nan=False)
    slippage_bps: float = Field(default=5,ge=0,le=100,allow_inf_nan=False)

class DeployRequest(BaseModel):
    instrument_id: str
    name: str | None = None
    strategy_type: Literal['SMA_CROSSOVER', 'EMA_CROSSOVER', 'RSI_EXTREME'] = 'SMA_CROSSOVER'
    params: dict[str, Any] | None = None
    fast: int = Field(default=20,ge=2,le=100)
    slow: int = Field(default=50,ge=3,le=200)
    initial: float = Field(default=100000,ge=100,allow_inf_nan=False)
    mode: Literal['paper', 'live'] = 'paper'

@strategy_router.post('/api/strategies/backtest')
def strategy(request: Request, body: BacktestRequest):
    instrument=request.app.state.store.instrument(body.instrument_id)
    if instrument['kind'] not in ('EQUITY','ETF','INDEX'):
        raise ValueError('This strategy tester supports stocks, ETFs and index studies only.')
    data=request.app.state.market.history(body.instrument_id,'D',365,user_id=get_user_id(request))
    if data.get('partial'):
        raise BrokerError('Backtest blocked: historical data is incomplete. Try again when Kotak history is available.')
    return {**backtest(data['candles'],body.initial,body.fast,body.slow,body.fee_bps,body.slippage_bps),
            'source':data['source'],'instrument':instrument['symbol'],'note':data['note']}

@strategy_router.post('/api/strategies/deploy')
def deploy_strategy(request: Request, body: DeployRequest):
    user_id = get_user_id(request)
    params = body.params or {'fast': body.fast, 'slow': body.slow}
    sid = request.app.state.strategy_engine.deploy(
        instrument_id=body.instrument_id,
        strategy_type=body.strategy_type,
        params=params,
        initial=body.initial,
        mode=body.mode,
        name=body.name,
        user_id=user_id
    )
    request.app.state.strategy_engine.pause(sid,user_id=user_id)
    return {'id':sid,'status':'PAUSED','note':'Saved for paper testing. Automatic execution awaits a connected strategy market feed.'}

@strategy_router.get('/api/strategies/active')
def active_strategies(request: Request):
    user_id = get_user_id(request)
    return request.app.state.strategy_engine.list_active(user_id=user_id)

@strategy_router.get('/api/strategies/{sid}')
def get_strategy(request: Request, sid: str):
    user_id = get_user_id(request)
    strat = request.app.state.strategy_engine.get_strategy(sid, user_id=user_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strat

@strategy_router.get('/api/strategies/{sid}/signals')
def strategy_signals(request: Request, sid: str, limit: int = 50):
    user_id = get_user_id(request)
    strat = request.app.state.strategy_engine.get_strategy(sid, user_id=user_id)
    if not strat:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return request.app.state.store.get_signals(user_id=user_id, strategy_id=sid, limit=limit)

@strategy_router.get('/api/signals/recent')
def recent_signals(request: Request, limit: int = 50):
    user_id = get_user_id(request)
    return request.app.state.store.get_signals(user_id=user_id, limit=limit)

@strategy_router.delete('/api/strategies/{sid}')
def stop_strategy(request: Request, sid: str):
    user_id = get_user_id(request)
    try:
        request.app.state.strategy_engine.stop(sid, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {'ok': True}

@strategy_router.post('/api/strategies/{sid}/pause')
def pause_strategy(request: Request, sid: str):
    user_id = get_user_id(request)
    try:
        request.app.state.strategy_engine.pause(sid, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {'ok': True}

@strategy_router.post('/api/strategies/{sid}/resume')
def resume_strategy(request: Request, sid: str):
    user_id = get_user_id(request)
    if not request.app.state.strategy_engine.get_strategy(sid,user_id=user_id):
        raise HTTPException(404,'Strategy not found')
    raise HTTPException(503,'Automatic execution is unavailable until the strategy market feed is connected. Historical backtests remain available.')

