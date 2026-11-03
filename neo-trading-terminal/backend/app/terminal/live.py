"""Manual broker trading and portfolio access for the current user."""
import json
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from app.brokers.base_broker import BrokerError
from app.terminal.risk import RiskViolationError
from app.terminal.portfolio import snapshot

live_router=APIRouter(prefix='/live',tags=['live'])


class LiveOrder(BaseModel):
    instrument_id: str = Field(max_length=100)
    side: Literal['BUY','SELL']
    quantity: int = Field(strict=True,gt=0,le=10000)
    order_type: Literal['MARKET','LIMIT'] = 'MARKET'
    limit_price: float | None = Field(default=None,gt=0,allow_inf_nan=False)
    product: Literal['MIS','NRML','CNC'] | None = None
    request_id: UUID

    @model_validator(mode='after')
    def limit_required(self):
        if self.order_type=='LIMIT' and self.limit_price is None:
            raise ValueError('A limit order needs a limit price.')
        if self.order_type=='MARKET' and self.limit_price is not None:
            raise ValueError('Market orders cannot include a limit price.')
        return self


def context(request):
    user=getattr(request.state,'user',None)
    if not user:
        raise HTTPException(401,'Sign in to access your Kotak account.')
    uid=user['id']
    market=request.app.state.market
    if not market.get_session(uid).broker.is_authenticated:
        raise HTTPException(401,'Your Kotak session has expired. Sign in again.')
    return market,request.app.state.store,uid


@live_router.get('')
def account(request: Request, refresh: bool=False):
    market,store,uid=context(request)
    return snapshot(market,store,uid,force=refresh)


@live_router.post('/orders',status_code=201)
def place_order(body: LiveOrder,request: Request):
    market,store,uid=context(request)
    if not request.app.state.config.live_trading_enabled:
        raise HTTPException(403,'Live order execution is disabled on this server.')
    item=store.instrument(body.instrument_id)
    derivative=item['kind'] in ('OPTION','FUTURE')
    if item['kind'] not in ('EQUITY','ETF','OPTION','FUTURE') or item['exchange'] not in ('nse_cm','bse_cm','nse_fo','bse_fo'):
        raise HTTPException(422,'Choose a tradable stock, ETF, future or option.')
    if derivative and (not item.get('expiry') or item['expiry']<date.today().isoformat()):
        raise HTTPException(422,'This derivative has expired or has no verified expiry.')
    if derivative and body.quantity%item['lot_size']:
        raise HTTPException(422,'Derivative quantities must be whole lots.')
    if body.limit_price is not None and Decimal(str(body.limit_price))%Decimal(str(item['tick_size'])):
        raise HTTPException(422,'Limit price must match the instrument tick size.')
    product=body.product or ('NRML' if derivative else 'CNC')
    if (derivative and product=='CNC') or (not derivative and product=='NRML'):
        raise HTTPException(422,'Choose a product supported by this instrument.')
    request_id=str(body.request_id)
    payload=json.dumps(body.model_dump(mode='json'),sort_keys=True)
    # Retries cannot submit a second order, including after a timeout or restart.
    with market.lock:
        with store.connect() as db:
            previous=db.execute('SELECT payload,result FROM live_requests WHERE user_id=? AND request_id=?',(uid,request_id)).fetchone()
        if previous:
            if previous['payload']!=payload:
                raise HTTPException(409,'This request ID was already used for another order.')
            if previous['result']:
                return json.loads(previous['result'])
            raise HTTPException(409,'This order may have reached Kotak. Check your broker order book before creating another order.')
        rows=market.quotes([item['id']],user_id=uid)
        if not rows or rows[0].get('source')!='kotak':
            raise HTTPException(503,'A verified Kotak quote is required to place an order.')
        try:
            request.app.state.risk_manager.for_user(uid).validate_order(item['symbol'],body.side,body.quantity,body.limit_price,rows[0]['ltp'])
        except RiskViolationError as exc:
            store.audit(uid,'live_order_rejected',exc.code)
            raise HTTPException(400,f'Risk Guardrail Violation: {exc.message}') from None
        with store.connect() as db:
            db.execute('INSERT INTO live_requests(user_id,request_id,payload) VALUES (?,?,?)',(uid,request_id,payload))
        try:
            result=market.call('place_order',user_id=uid,exchange_segment=item['exchange'],product=product,
                               price=str(body.limit_price or 0),order_type='L' if body.order_type=='LIMIT' else 'MKT',
                               quantity=str(body.quantity),validity='DAY',trading_symbol=item['symbol'],
                               transaction_type='B' if body.side=='BUY' else 'S')
        except BrokerError:
            raise HTTPException(502,'Kotak did not confirm this order. Check the broker order book before trying another order.') from None
        data=result.get('data',result) if isinstance(result,dict) else {}
        order_id=data.get('nOrdNo') if isinstance(data,dict) else None
        if not order_id:
            raise HTTPException(502,'Kotak did not return an order number. Check the broker order book before creating another order.')
        response={'id':str(order_id),'status':'SUBMITTED'}
        with store.connect() as db:
            db.execute('UPDATE live_requests SET result=? WHERE user_id=? AND request_id=?',(json.dumps(response),uid,request_id))
        market.get_session(uid).portfolio_cache=None
        store.audit(uid,'live_order_submitted',f'{body.side} {body.quantity} {item["symbol"]}; broker order {order_id}')
        return response


@live_router.delete('/orders/{identifier}')
def cancel_order(identifier: str,request: Request):
    market,store,uid=context(request)
    if not request.app.state.config.live_trading_enabled:
        raise HTTPException(403,'Live order execution is disabled on this server.')
    current=snapshot(market,store,uid,force=True)
    owned=next((o for o in current['orders'] if o['id']==identifier),None)
    if not owned:
        raise HTTPException(404,'Order not found in your Kotak account.')
    if owned.get('side') not in ('BUY','SELL') or owned['status'] not in ('OPEN','PENDING','TRIGGER_PENDING'):
        raise HTTPException(409,'This order is no longer cancellable.')
    market.call('cancel_order',user_id=uid,order_no=identifier,amq='NO')
    market.get_session(uid).portfolio_cache=None
    return {'ok':True}
