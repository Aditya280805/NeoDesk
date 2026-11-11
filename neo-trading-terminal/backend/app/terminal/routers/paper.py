
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID
from app.auth.dependencies import get_request_user_id as get_user_id
from app.brokers.base_broker import BrokerError

paper_router = APIRouter()

class PaperOrder(BaseModel):
    instrument_id: str = Field(max_length=100)
    side: Literal['BUY','SELL']
    quantity: int = Field(strict=True,gt=0,le=10000)
    order_type: Literal['MARKET','LIMIT'] = 'MARKET'
    limit_price: float | None = Field(default=None,gt=0,allow_inf_nan=False)
    request_id: UUID

@paper_router.get('/api/paper')
def account(request: Request):
    user_id = get_user_id(request)
    store = request.app.state.store
    market = request.app.state.market
    paper = request.app.state.paper
    with store.connect() as db:
        ids=[r[0] for r in db.execute('SELECT instrument_id FROM positions WHERE user_id=? AND quantity>0 UNION SELECT instrument_id FROM futures_positions WHERE user_id=? AND quantity<>0', (user_id, user_id))]
        source=db.execute('SELECT value FROM metadata WHERE key=?',('paper_source' if user_id==1 else f'paper_source:{user_id}',)).fetchone()
    quotes={}
    error=None
    current_source=market.get_session(user_id).source
    if source and source[0]!=current_source:
        error='Connect the original data source to value these holdings. Reset the account to change sources.'
    else:
        try:
            # We must resolve quote_map manually as it is not passed
            def quote_map(ids):
                result={}
                for start in range(0,len(ids),50):
                    result.update({q['id']:q for q in market.quotes(ids[start:start+50],user_id=user_id)})
                return result
            quotes=quote_map(ids)
        except (BrokerError,ValueError):
            error='Valuation unavailable; cash and holdings are retained.'
    return {**paper.snapshot(user_id, quotes),'source':source[0] if source else current_source,'valuation_error':error}

@paper_router.post('/api/paper/orders',status_code=201)
def order(request: Request, body: PaperOrder):
    user_id = get_user_id(request)
    instrument=request.app.state.store.instrument(body.instrument_id)
    if body.order_type=='LIMIT' and body.limit_price is None:
        raise ValueError('A limit order needs a limit price.')
    rows=request.app.state.market.quotes([body.instrument_id],user_id=user_id)
    if not rows:
        raise BrokerError('No usable price is available for this instrument. Order was not submitted.')
    quote=rows[0]
    return request.app.state.paper.submit(instrument,body.side,body.quantity,body.order_type,body.limit_price,str(body.request_id),quote,user_id=user_id)

@paper_router.delete('/api/paper/orders/{identifier}')
def cancel(request: Request, identifier: str):
    user_id = get_user_id(request)
    request.app.state.paper.cancel(user_id, identifier)
    return {'ok':True}

@paper_router.post('/api/paper/reset')
def reset(request: Request, body: dict):
    if body.get('confirmation')!='RESET PAPER ACCOUNT':
        raise ValueError('Type RESET PAPER ACCOUNT to confirm.')
    user_id = get_user_id(request)
    with request.app.state.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM positions WHERE user_id=?', (user_id,))
        db.execute('DELETE FROM futures_positions WHERE user_id=?', (user_id,))
        db.execute('DELETE FROM orders WHERE user_id=?', (user_id,))
        db.execute('UPDATE account SET cash=initial,realized=0 WHERE user_id=?', (user_id,))
        db.execute('DELETE FROM metadata WHERE key=?',('paper_source' if user_id==1 else f'paper_source:{user_id}',))
    request.app.state.store.audit(user_id, 'paper_reset', 'User confirmed paper account reset.')
    return account(request)

