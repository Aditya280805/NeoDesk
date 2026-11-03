from typing import Optional, Dict
from pydantic import BaseModel, Field
from threading import RLock
import datetime
import json

class RiskViolationError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code
        self.message = message

class RiskLimits(BaseModel):
    max_order_value: float = Field(default=500000.0,gt=0,allow_inf_nan=False)
    max_daily_loss: float = Field(default=25000.0,gt=0,allow_inf_nan=False)
    max_price_deviation_pct: float = Field(default=10.0,gt=0,le=100,allow_inf_nan=False)
    max_quantity_per_order: int = Field(default=10000,gt=0,le=10000)

class RiskManager:
    def __init__(self, limits: Optional[RiskLimits] = None, store=None, user_id: int=1):
        self.limits = limits or RiskLimits()
        self.kill_switch_active = False
        self.kill_switch_reason: Optional[str] = None
        self.daily_realized_pnl = 0.0
        self.date = datetime.date.today()
        self._users = {}
        self._users_lock = RLock()
        self._store,self._user_id=store,user_id
        if store:
            with store.connect() as db:
                saved=db.execute('SELECT value FROM metadata WHERE key=?',(f'risk:{user_id}',)).fetchone()
            if saved:
                state=json.loads(saved[0])
                self.limits=RiskLimits(**state['limits'])
                self.kill_switch_active=state['kill_switch_active']
                self.kill_switch_reason=state['kill_switch_reason']

    def save(self):
        if self._store:
            state={'limits':self.limits.model_dump(),'kill_switch_active':self.kill_switch_active,
                   'kill_switch_reason':self.kill_switch_reason}
            with self._store.connect() as db:
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(f'risk:{self._user_id}',json.dumps(state)))

    def for_user(self, user_id: int):
        if user_id == 1:
            return self
        with self._users_lock:
            if user_id not in self._users:
                self._users[user_id] = RiskManager(store=self._store,user_id=user_id)
            return self._users[user_id]
        
    def _check_date(self):
        today = datetime.date.today()
        if today != self.date:
            self.daily_realized_pnl = 0.0
            self.date = today

    def validate_order(self, instrument: str, side: str, quantity: int, price: Optional[float], ltp: float):
        self._check_date()
        
        if self.kill_switch_active:
            raise RiskViolationError(f"Kill switch is active. Reason: {self.kill_switch_reason}", "KILL_SWITCH_ACTIVE")
            
        if quantity <= 0:
            raise RiskViolationError("Quantity must be positive", "INVALID_QUANTITY")
            
        if quantity > self.limits.max_quantity_per_order:
            raise RiskViolationError(f"Quantity {quantity} exceeds max {self.limits.max_quantity_per_order}", "MAX_QUANTITY_EXCEEDED")
            
        if ltp <= 0:
            raise RiskViolationError("Invalid LTP (must be positive)", "INVALID_LTP")
            
        reference_price = price if price is not None and price > 0 else ltp
        
        order_value = quantity * reference_price
        if order_value > self.limits.max_order_value:
            raise RiskViolationError(f"Order value {order_value} exceeds max {self.limits.max_order_value}", "MAX_ORDER_VALUE_EXCEEDED")
            
        if price is not None and price > 0:
            deviation_pct = abs(price - ltp) / ltp * 100.0
            if deviation_pct > self.limits.max_price_deviation_pct:
                raise RiskViolationError(f"Price deviation {deviation_pct:.2f}% exceeds max {self.limits.max_price_deviation_pct}%", "PRICE_COLLAR_EXCEEDED")
                
        if self.daily_realized_pnl < -self.limits.max_daily_loss:
            raise RiskViolationError(f"Daily loss {-self.daily_realized_pnl} exceeds max {self.limits.max_daily_loss}", "MAX_DAILY_LOSS_EXCEEDED")
            
    def trigger_kill_switch(self, reason: str):
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        self.save()
        
    def reset_kill_switch(self):
        self.kill_switch_active = False
        self.kill_switch_reason = None
        self.save()
        
    def record_trade_pnl(self, realized_pnl: float):
        self._check_date()
        self.daily_realized_pnl += realized_pnl
            
    def get_status(self) -> Dict:
        self._check_date()
        return {
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reason": self.kill_switch_reason,
            "daily_realized_pnl": self.daily_realized_pnl,
            "limits": self.limits.model_dump()
        }
