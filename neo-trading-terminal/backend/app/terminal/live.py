from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID

from app.brokers.base_broker import BrokerError
from app.terminal.risk import RiskViolationError
from neo_api_client.exceptions import (
    AuthenticationError,
    ValidationError,
    RateLimitError,
    OrderError,
    NeoAPIException
)

live_router = APIRouter(prefix="/live", tags=["live"])


class LiveOrder(BaseModel):
    instrument_id: str = Field(max_length=100)
    side: Literal['BUY', 'SELL']
    quantity: int = Field(strict=True, gt=0, le=10000)
    order_type: Literal['MARKET', 'LIMIT'] = 'MARKET'
    limit_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    product: Literal['MIS', 'NRML', 'CNC'] = 'MIS'
    request_id: UUID


@live_router.get("")
def account(request: Request):
    """
    Get live positions, margin/limits, and open orders.
    Matches the schema expected by the frontend for a unified dashboard.
    """
    market = request.app.state.market
    store = request.app.state.store
    if not market.broker.is_authenticated:
        raise HTTPException(401, 'Complete Kotak TOTP/MPIN login in Connections.')
    
    try:
        limits = market.call('limits')
        positions = market.call('positions')
        orders_rep = market.call('order_report')
    except BrokerError as e:
        raise HTTPException(503, str(e))

    # Format the data similarly to paper.snapshot
    # For now, proxy raw fields that frontend might need or normalize them
    # Note: frontend needs 'available', 'equity', 'positions', 'orders'
    
    avail = 0
    if isinstance(limits, dict) and 'Net' in limits:
        try:
            avail = float(limits['Net'])
        except:
            pass

    normalized_positions = []
    if isinstance(positions, dict) and isinstance(positions.get('data'), list):
        for r in positions['data']:
            normalized_positions.append({
                'instrument_id': str(r.get('nS', r.get('trdSym'))),
                'symbol': r.get('trdSym'),
                'quantity': int(r.get('netQty', 0)),
                'average_price': float(r.get('avgPrc', 0) if r.get('avgPrc') else 0),
                'pnl': float(r.get('mtm', 0)),
                'ltp': float(r.get('ltp', 0) if r.get('ltp') else 0),
                'kind': 'LIVE'
            })

    normalized_orders = []
    if isinstance(orders_rep, dict) and isinstance(orders_rep.get('data'), list):
        for o in orders_rep['data']:
            status = o.get('ordSt')
            # normalized paper orders have: id, side, quantity, order_type, limit_price, status, created_at, instrument_id
            normalized_orders.append({
                'id': str(o.get('nOrdNo')),
                'instrument_id': str(o.get('nS', o.get('trdSym'))),
                'side': 'BUY' if o.get('trnsTp') == 'B' else 'SELL',
                'quantity': int(o.get('qty', 0)),
                'order_type': o.get('ordTp'),
                'limit_price': float(o.get('prc', 0)),
                'status': 'OPEN' if status in ('open', 'pending') else 'FILLED' if status == 'complete' else 'CANCELLED',
                'created_at': o.get('ordDtTm')
            })

    return {
        'initial': avail,
        'cash': avail,
        'available': avail,
        'equity': avail, # Approximation for now
        'positions': [p for p in normalized_positions if p['quantity'] != 0],
        'orders': normalized_orders,
        'source': 'kotak',
        'valuation_error': None
    }


@live_router.post("/orders", status_code=201)
def place_order(body: LiveOrder, request: Request):
    market = request.app.state.market
    store = request.app.state.store
    
    if not market.broker.is_authenticated:
        raise HTTPException(401, 'Complete Kotak TOTP/MPIN login in Connections.')
    
    instrument = store.instrument(body.instrument_id)
    
    exch_seg = instrument.get('exchange', 'nse_cm')
    neo_symbol = instrument.get('neo_symbol', instrument.get('symbol'))
    
    tx_type = 'B' if body.side == 'BUY' else 'S'
    order_type = 'L' if body.order_type == 'LIMIT' else 'MKT'
    price = str(body.limit_price) if body.limit_price else "0"
    
    # Fetch quote for LTP
    rows = market.quotes([body.instrument_id])
    if not rows:
        raise HTTPException(400, 'No usable price is available for this instrument.')
    ltp = rows[0].get('ltp', 0.0)

    # Pre-trade Risk Check
    risk_manager = request.app.state.risk_manager
    try:
        risk_manager.validate_order(
            instrument=neo_symbol,
            side=body.side,
            quantity=body.quantity,
            price=body.limit_price,
            ltp=float(ltp)
        )
    except RiskViolationError as e:
        store.audit('live_order_rejected', f"Risk violation: {e.message}")
        raise HTTPException(400, f"Risk Guardrail Violation: {e.message}")

    try:
        res = market.broker.client.place_order(
            exchange_segment=exch_seg,
            product=body.product,
            price=price,
            order_type=order_type,
            quantity=str(body.quantity),
            validity="DAY",
            trading_symbol=neo_symbol,
            transaction_type=tx_type
        )
        store.audit('live_order_submitted', f"Live order submitted for {body.quantity} {neo_symbol}")
        return {"ok": True, "data": res}
    except ValidationError as e:
        raise HTTPException(422, f"Invalid order parameters: {e}")
    except AuthenticationError:
        raise HTTPException(401, "Session expired. Please log in again.")
    except OrderError as e:
        raise HTTPException(400, f"Order placement failed: {e}")
    except RateLimitError:
        raise HTTPException(429, "Rate limit exceeded. Try again later.")
    except NeoAPIException as e:
        raise HTTPException(502, f"Kotak API Error: {e}")


@live_router.delete("/orders/{identifier}")
def cancel_order(identifier: str, request: Request, amq: str = "NO"):
    market = request.app.state.market
    if not market.broker.is_authenticated:
        raise HTTPException(401, 'Complete Kotak TOTP/MPIN login in Connections.')
        
    try:
        res = market.broker.client.cancel_order(order_no=identifier, amq=amq)
        return {"ok": True, "data": res}
    except Exception as e:
        raise HTTPException(400, f"Failed to cancel order: {e}")
