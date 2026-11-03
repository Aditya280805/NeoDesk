import uuid
import time
from typing import Dict, Any, List, Optional
import asyncio
import logging
from app.terminal.signals import Signal, IndicatorEvaluator

logger = logging.getLogger(__name__)

class StrategyEngine:
    """
    Core execution engine for automated trading strategies.
    
    Manages the lifecycle, evaluation, and execution of trading signals against 
    paper strategies. Live algorithm execution is unavailable until its broker
    acknowledgements and fills can be reconciled per account.
    """
    def __init__(self, store, market, paper, risk_manager=None):
        """Initialize the StrategyEngine with required dependencies."""
        self.store = store
        self.market = market
        self.paper = paper
        self.risk_manager = risk_manager
        self.strategies: Dict[str, Dict[str, Any]] = {}
        self.evaluators: Dict[str, IndicatorEvaluator] = {}
        self._load_persisted_strategies()

    def _load_persisted_strategies(self):
        """Restore running strategies from database on engine initialization."""
        try:
            persisted = self.store.list_strategies(status='RUNNING')
            for item in persisted:
                sid = item['id']
                instrument_id = item['instrument_id']
                token = item.get('token', '')
                if not token:
                    token = self._resolve_token(instrument_id)
                    item['token'] = token
                
                params = item.get('params', {})
                history_depth = max(
                    int(params.get('slow', 30)) + 10,
                    int(params.get('period', 14)) + 10,
                    50
                )
                
                if item.get('mode') != 'paper':
                    continue
                closes = self._fetch_history(instrument_id, history_depth, item.get('user_id',1))
                evaluator = IndicatorEvaluator(
                    strategy_id=sid,
                    instrument_id=instrument_id,
                    strategy_type=item.get('strategy_type', 'SMA_CROSSOVER'),
                    params=params
                )
                
                self.strategies[sid] = {
                    **item,
                    'closes': closes,
                    'last_eval': None,
                    'lock': asyncio.Lock()
                }
                self.evaluators[sid] = evaluator
                self.store.watch(item.get('user_id',1),instrument_id)
        except Exception as e:
            logger.error(f"Error loading persisted strategies: {e}")

    def _resolve_token(self, instrument_id: str) -> str:
        try:
            instrument = self.store.instrument(instrument_id)
            token = instrument.get('exchange_token') or instrument.get('token', '')
            if not token:
                with self.store.connect() as db:
                    row = db.execute("SELECT instrument_token FROM instruments WHERE id=?", (instrument_id,)).fetchone()
                    if row:
                        token = row[0]
            return str(token)
        except Exception:
            return ''

    def _fetch_history(self, instrument_id: str, depth: int, user_id: int=1) -> List[float]:
        try:
            history = self.market.history(instrument_id, 'D', depth, user_id=user_id)
            return [float(c['close']) for c in history.get('candles', [])][-depth:]
        except Exception as e:
            logger.error(f"Failed to fetch history for {instrument_id}: {e}")
            return []

    def deploy(
        self, 
        instrument_id: str, 
        strategy_type: str = 'SMA_CROSSOVER',
        params: Optional[Dict[str, Any]] = None,
        initial: float = 100000.0, 
        mode: str = 'paper',
        name: Optional[str] = None,
        fast: Optional[int] = None,
        slow: Optional[int] = None,
        user_id: int = 1
    ) -> str:
        if mode != 'paper':
            raise ValueError('Automated live strategies are unavailable. Use a reviewed manual Kotak order.')
        params = params or {}
        if fast is not None and 'fast' not in params:
            params['fast'] = fast
        if slow is not None and 'slow' not in params:
            params['slow'] = slow

        token = self._resolve_token(instrument_id)
        sid = str(uuid.uuid4())
        strat_name = name or f"{strategy_type} on {instrument_id}"

        depth = max(
            int(params.get('slow', 30)) + 10,
            int(params.get('period', 14)) + 10,
            50
        )
        closes = self._fetch_history(instrument_id, depth, user_id)

        strat_data = {
            'id': sid,
            'user_id': user_id,
            'name': strat_name,
            'strategy_type': strategy_type,
            'instrument_id': instrument_id,
            'token': token,
            'params': params,
            'mode': mode,
            'cash': float(initial),
            'held': 0,
            'realized_pnl': 0.0,
            'total_trades': 0,
            'status': 'RUNNING',
            'created_at': time.time(),
            'updated_at': time.time()
        }

        # Persist to SQLite
        self.store.save_strategy(strat_data, user_id=user_id)

        evaluator = IndicatorEvaluator(
            strategy_id=sid,
            instrument_id=instrument_id,
            strategy_type=strategy_type,
            params=params
        )

        self.strategies[sid] = {
            **strat_data,
            'closes': closes,
            'entry_cost': 0.0,
            'last_eval': None,
            'lock': asyncio.Lock()
        }
        self.evaluators[sid] = evaluator

        # Ensure the instrument is watched for WebSocket/polling stream
        try:
            self.store.watch(user_id, instrument_id)
        except Exception:
            pass

        return sid

    def stop(self, sid: str, user_id: Optional[int] = None):
        if sid not in self.strategies:
            self._update_saved_status(sid,user_id,'STOPPED')
            return
        if sid in self.strategies:
            strat = self.strategies[sid]
            if user_id is not None and strat.get('user_id', 1) != user_id:
                raise ValueError("Unauthorized access to strategy")
            strat['status'] = 'STOPPED'
            self.store.update_strategy_state(
                sid=sid,
                cash=strat['cash'],
                held=strat['held'],
                realized_pnl=strat.get('realized_pnl', 0.0),
                total_trades=strat.get('total_trades', 0),
                status='STOPPED'
            )

    def pause(self, sid: str, user_id: Optional[int] = None):
        if sid not in self.strategies:
            self._update_saved_status(sid,user_id,'PAUSED')
            return
        if sid in self.strategies:
            strat = self.strategies[sid]
            if user_id is not None and strat.get('user_id', 1) != user_id:
                raise ValueError("Unauthorized access to strategy")
            strat['status'] = 'PAUSED'
            self.store.update_strategy_state(
                sid=sid,
                cash=strat['cash'],
                held=strat['held'],
                realized_pnl=strat.get('realized_pnl', 0.0),
                total_trades=strat.get('total_trades', 0),
                status='PAUSED'
            )

    def _update_saved_status(self,sid,user_id,status):
        saved=self.store.get_strategy(sid)
        if not saved:
            raise ValueError('Strategy not found')
        if user_id is not None and saved['user_id']!=user_id:
            raise ValueError('Unauthorized access to strategy')
        self.store.update_strategy_state(sid,saved['cash'],saved['held'],status=status)

    def resume(self, sid: str, user_id: Optional[int] = None):
        if sid in self.strategies:
            strat = self.strategies[sid]
            if user_id is not None and strat.get('user_id', 1) != user_id:
                raise ValueError("Unauthorized access to strategy")
            strat['status'] = 'RUNNING'
            self.store.update_strategy_state(
                sid=sid,
                cash=strat['cash'],
                held=strat['held'],
                realized_pnl=strat.get('realized_pnl', 0.0),
                total_trades=strat.get('total_trades', 0),
                status='RUNNING'
            )

    def remove(self, sid: str, user_id: Optional[int] = None):
        if sid in self.strategies:
            self.stop(sid, user_id=user_id)
            del self.strategies[sid]
        if sid in self.evaluators:
            del self.evaluators[sid]

    def get_strategy(self, sid: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if sid in self.strategies:
            strat = dict(self.strategies[sid])
            if user_id is not None and strat.get('user_id', 1) != user_id:
                return None
            return strat
        return self.store.get_strategy(sid, user_id)

    def list_active(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        # Sync with database records to return clean serializable format
        db_strats = self.store.list_strategies(user_id=user_id)
        # Merge latest in-memory cash/held states
        for s in db_strats:
            sid = s['id']
            if sid in self.strategies:
                mem = self.strategies[sid]
                s['cash'] = mem['cash']
                s['held'] = mem['held']
                s['realized_pnl'] = mem.get('realized_pnl', 0.0)
                s['total_trades'] = mem.get('total_trades', 0)
                s['status'] = mem['status']
        return db_strats


    async def on_tick(self, token: str, ltp: float):
        token_str = str(token)
        for sid, strat in list(self.strategies.items()):
            if strat['status'] != 'RUNNING':
                continue

            strat_token = str(strat.get('token', ''))
            if strat_token and strat_token != token_str:
                continue

            if 'lock' not in strat:
                strat['lock'] = asyncio.Lock()

            async with strat['lock']:
                if strat['status'] != 'RUNNING':
                    continue

                strat['last_eval'] = time.time()
                evaluator = self.evaluators.get(sid)
                if not evaluator:
                    continue

                closes = strat.get('closes', [])
                signal: Optional[Signal] = evaluator.evaluate(closes, ltp)

                if signal:
                    # 1. Record signal in DB
                    try:
                        self.store.record_signal(strat.get('user_id', 1), signal)
                    except Exception as e:
                        logger.error(f"Failed to record signal: {e}")


                    # 2. Broadcast signal over WebSocket
                    try:
                        from app.websocket.manager import manager
                        await manager.broadcast({"type": "SIGNAL", "data": signal.to_dict(), "user_id":strat.get('user_id',1)})
                    except Exception as e:
                        logger.error(f"Failed to broadcast signal: {e}")

                    # 3. Execute order if actionable
                    try:
                        instrument = self.store.instrument(strat['instrument_id'])
                    except Exception as e:
                        logger.error(f"Failed to lookup instrument for strategy {sid}: {e}")
                        continue

                    if signal.action == 'BUY' and strat['held'] == 0:
                        qty = int(strat['cash'] / ltp)
                        if qty > 0:
                            cost = qty * ltp
                            success = await self._execute_order(strat, instrument, 'BUY', qty, ltp)
                            if success:
                                strat['held'] = qty
                                strat['entry_cost'] = cost
                                strat['cash'] -= cost
                                strat['total_trades'] = strat.get('total_trades', 0) + 1
                                self.store.update_strategy_state(
                                    sid, 
                                    cash=strat['cash'], 
                                    held=strat['held'], 
                                    realized_pnl=strat.get('realized_pnl', 0.0), 
                                    total_trades=strat['total_trades']
                                )

                    elif signal.action == 'SELL' and strat['held'] > 0:
                        qty = strat['held']
                        proceeds = qty * ltp
                        entry_cost = strat.get('entry_cost', proceeds)
                        pnl = proceeds - entry_cost
                        success = await self._execute_order(strat, instrument, 'SELL', qty, ltp)
                        if success:
                            strat['realized_pnl'] = strat.get('realized_pnl', 0.0) + pnl
                            strat['cash'] += proceeds
                            strat['held'] = 0
                            strat['total_trades'] = strat.get('total_trades', 0) + 1
                            self.store.update_strategy_state(
                                sid, 
                                cash=strat['cash'], 
                                held=strat['held'], 
                                realized_pnl=strat['realized_pnl'], 
                                total_trades=strat['total_trades']
                            )

    async def _execute_order(self, strat: dict, instrument: dict, side: str, quantity: int, price: float) -> bool:
        logger.info(f"Strategy {strat['id']} executing {side} {quantity} {instrument['symbol']} @ {price} in {strat['mode']} mode")
        
        if strat['mode'] == 'paper':
            quote = {'id': strat['instrument_id'], 'ltp': price, 'close': price, 'source': self.market.get_session(strat.get('user_id',1)).source}
            self.paper.submit(
                instrument=instrument,
                side=side,
                quantity=quantity,
                order_type='MARKET',
                price=None,
                request_id=str(uuid.uuid4()),
                quote=quote,
                user_id=strat.get('user_id', 1)
            )

            return True
        return False
