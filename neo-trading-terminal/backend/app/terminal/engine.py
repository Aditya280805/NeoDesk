import uuid
import time
from typing import Dict, Any, List
import asyncio
import logging

logger = logging.getLogger(__name__)

class StrategyEngine:
    def __init__(self, store, market, paper):
        self.store = store
        self.market = market
        self.paper = paper
        self.strategies: Dict[str, Dict[str, Any]] = {}

    def deploy(self, instrument_id: str, fast: int, slow: int, initial: float, mode: str) -> str:
        instrument = self.store.instrument(instrument_id)
        token = instrument['exchange_token'] if 'exchange_token' in instrument else instrument.get('token', '')
        # Fallback to fetching it from the DB directly if missing in the simplified dictionary
        if not token:
            with self.store.connect() as db:
                row = db.execute("SELECT instrument_token FROM instruments WHERE id=?", (instrument_id,)).fetchone()
                if row:
                    token = row[0]
                    
        sid = str(uuid.uuid4())
        
        # Fetch historical data to warm up the SMAs
        try:
            history = self.market.history(instrument_id, 'D', slow + 5)
            closes = [c['close'] for c in history.get('candles', [])][-slow:]
        except Exception as e:
            logger.error(f"Failed to fetch history for {instrument_id}: {e}")
            closes = []
            
        self.strategies[sid] = {
            'id': sid,
            'instrument_id': instrument_id,
            'token': token,
            'fast': fast,
            'slow': slow,
            'initial': initial,
            'mode': mode,
            'cash': initial,
            'held': 0,
            'closes': closes,
            'status': 'RUNNING',
            'created_at': time.time(),
            'last_eval': None
        }
        
        # Ensure the instrument is watched so we get ticks
        self.store.watch(instrument_id)
        return sid

    def stop(self, sid: str):
        if sid in self.strategies:
            self.strategies[sid]['status'] = 'STOPPED'
            
    def remove(self, sid: str):
        if sid in self.strategies:
            del self.strategies[sid]

    def list_active(self) -> List[Dict[str, Any]]:
        return list(self.strategies.values())

    async def on_tick(self, token: str, ltp: float):
        # We received a tick from the websocket. 
        # Evaluate any RUNNING strategies that listen to this token.
        for sid, strat in self.strategies.items():
            if strat['status'] != 'RUNNING':
                continue
                
            if strat['token'] != token and str(strat['token']) != str(token):
                continue
                
            strat['last_eval'] = time.time()
            
            # Simple tick-based moving average evaluation
            closes = strat['closes']
            if not closes:
                closes.append(ltp)
                
            # Treat the current LTP as the latest "close"
            current_window = closes + [ltp]
            if len(current_window) > strat['slow']:
                current_window = current_window[-strat['slow']:]
                
            if len(current_window) >= strat['slow']:
                fast_sma = sum(current_window[-strat['fast']:]) / strat['fast']
                slow_sma = sum(current_window) / strat['slow']
                
                instrument = self.store.instrument(strat['instrument_id'])
                
                if fast_sma > slow_sma and strat['held'] == 0:
                    # BUY signal
                    qty = int(strat['cash'] / ltp)
                    if qty > 0:
                        strat['held'] = qty
                        strat['cash'] -= qty * ltp
                        await self._execute_order(strat, instrument, 'BUY', qty, ltp)
                        
                elif fast_sma < slow_sma and strat['held'] > 0:
                    # SELL signal
                    qty = strat['held']
                    strat['cash'] += qty * ltp
                    strat['held'] = 0
                    await self._execute_order(strat, instrument, 'SELL', qty, ltp)

    async def _execute_order(self, strat: dict, instrument: dict, side: str, quantity: int, price: float):
        logger.info(f"Strategy {strat['id']} executing {side} {quantity} {instrument['symbol']} @ {price} in {strat['mode']} mode")
        
        if strat['mode'] == 'paper':
            # Create a mock quote to satisfy paper.submit
            quote = {'id': strat['instrument_id'], 'ltp': price, 'close': price}
            self.paper.submit(
                instrument=instrument,
                side=side,
                quantity=quantity,
                order_type='MARKET',
                limit_price=None,
                request_id=str(uuid.uuid4()),
                quote=quote
            )
        elif strat['mode'] == 'live':
            # For live execution, we route through market.broker.client
            # Note: For production, we should map Kotak specific segments properly.
            try:
                # Basic market order placement logic mirroring live.py
                # This is a simplification for the engine
                pass 
            except Exception as e:
                logger.error(f"Failed to place live order for strategy {strat['id']}: {e}")
