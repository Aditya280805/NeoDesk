"""Technical indicator evaluation and algorithmic signal generation."""
import time
from dataclasses import dataclass, field, asdict
from typing import Literal, Dict, Any, List, Optional, Tuple

SignalAction = Literal['BUY', 'SELL', 'HOLD']

@dataclass
class Signal:
    strategy_id: str
    instrument_id: str
    action: SignalAction
    price: float
    timestamp: float = field(default_factory=time.time)
    indicator_type: str = 'SMA_CROSSOVER'
    metadata: Dict[str, Any] = field(default_factory=dict)
    order_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy_id': self.strategy_id,
            'instrument_id': self.instrument_id,
            'action': self.action,
            'price': round(float(self.price), 2),
            'timestamp': float(self.timestamp),
            'indicator_type': self.indicator_type,
            'metadata': self.metadata,
            'order_id': self.order_id
        }


def calculate_sma(series: List[float], period: int) -> Optional[float]:
    if len(series) < period or period <= 0:
        return None
    return sum(series[-period:]) / period


def calculate_ema(series: List[float], period: int) -> Optional[float]:
    if len(series) < period or period <= 0:
        return None
    k = 2.0 / (period + 1)
    # Initialize EMA with SMA of first period elements
    val = sum(series[:period]) / period
    for x in series[period:]:
        val = (x * k) + (val * (1.0 - k))
    return val


def calculate_rsi(series: List[float], period: int = 14) -> Optional[float]:
    if len(series) <= period or period <= 0:
        return None
    
    diffs = [series[i] - series[i - 1] for i in range(1, len(series))]
    if not diffs:
        return None

    gains = [max(d, 0.0) for d in diffs[:period]]
    losses = [max(-d, 0.0) for d in diffs[:period]]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    for d in diffs[period:]:
        gain = max(d, 0.0)
        loss = max(-d, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def evaluate_sma_crossover(closes: List[float], fast: int, slow: int) -> Tuple[SignalAction, Dict[str, Any]]:
    if fast >= slow or len(closes) < slow + 1:
        return 'HOLD', {'reason': 'Insufficient history'}

    # Current bar
    curr_fast = calculate_sma(closes, fast)
    curr_slow = calculate_sma(closes, slow)

    # Previous bar
    prev_fast = calculate_sma(closes[:-1], fast)
    prev_slow = calculate_sma(closes[:-1], slow)

    if None in (curr_fast, curr_slow, prev_fast, prev_slow):
        return 'HOLD', {'reason': 'Indicator calculation error'}

    metadata = {
        'curr_fast': round(curr_fast, 2),
        'curr_slow': round(curr_slow, 2),
        'prev_fast': round(prev_fast, 2),
        'prev_slow': round(prev_slow, 2),
    }

    # Bullish crossover (Golden cross)
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return 'BUY', metadata
    # Bearish crossover (Death cross)
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return 'SELL', metadata

    return 'HOLD', metadata


def evaluate_ema_crossover(closes: List[float], fast: int, slow: int) -> Tuple[SignalAction, Dict[str, Any]]:
    if fast >= slow or len(closes) < slow + 1:
        return 'HOLD', {'reason': 'Insufficient history'}

    curr_fast = calculate_ema(closes, fast)
    curr_slow = calculate_ema(closes, slow)

    prev_fast = calculate_ema(closes[:-1], fast)
    prev_slow = calculate_ema(closes[:-1], slow)

    if None in (curr_fast, curr_slow, prev_fast, prev_slow):
        return 'HOLD', {'reason': 'Indicator calculation error'}

    metadata = {
        'curr_fast': round(curr_fast, 2),
        'curr_slow': round(curr_slow, 2),
        'prev_fast': round(prev_fast, 2),
        'prev_slow': round(prev_slow, 2),
    }

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return 'BUY', metadata
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return 'SELL', metadata

    return 'HOLD', metadata


def evaluate_rsi_extreme(
    closes: List[float], 
    period: int = 14, 
    oversold: float = 30.0, 
    overbought: float = 70.0
) -> Tuple[SignalAction, Dict[str, Any]]:
    if len(closes) < period + 2:
        return 'HOLD', {'reason': 'Insufficient history'}

    curr_rsi = calculate_rsi(closes, period)
    prev_rsi = calculate_rsi(closes[:-1], period)

    if curr_rsi is None or prev_rsi is None:
        return 'HOLD', {'reason': 'RSI calculation error'}

    metadata = {
        'curr_rsi': curr_rsi,
        'prev_rsi': prev_rsi,
        'oversold': oversold,
        'overbought': overbought
    }

    # Rebound from oversold condition
    if (prev_rsi <= oversold and curr_rsi > oversold) or (curr_rsi < oversold):
        return 'BUY', metadata
    # Fall from overbought condition
    elif (prev_rsi >= overbought and curr_rsi < overbought) or (curr_rsi > overbought):
        return 'SELL', metadata

    return 'HOLD', metadata


class IndicatorEvaluator:
    """Stateful evaluator to debounce consecutive duplicate signals."""
    def __init__(self, strategy_id: str, instrument_id: str, strategy_type: str, params: Dict[str, Any]):
        self.strategy_id = strategy_id
        self.instrument_id = instrument_id
        self.strategy_type = strategy_type.upper()
        self.params = params
        self.last_action: SignalAction = 'HOLD'
        self.last_signal_time: float = 0.0
        self.cooldown_seconds: float = params.get('cooldown_seconds', 1.0)

    def evaluate(self, closes: List[float], current_price: float) -> Optional[Signal]:
        now = time.time()
        if now - self.last_signal_time < self.cooldown_seconds:
            return None

        # Build series incorporating current live tick as the latest close
        series = closes + [current_price] if closes else [current_price]

        action: SignalAction = 'HOLD'
        meta: Dict[str, Any] = {}

        if self.strategy_type == 'SMA_CROSSOVER':
            fast = int(self.params.get('fast', 10))
            slow = int(self.params.get('slow', 30))
            action, meta = evaluate_sma_crossover(series, fast, slow)
        elif self.strategy_type == 'EMA_CROSSOVER':
            fast = int(self.params.get('fast', 10))
            slow = int(self.params.get('slow', 30))
            action, meta = evaluate_ema_crossover(series, fast, slow)
        elif self.strategy_type == 'RSI_EXTREME':
            period = int(self.params.get('period', 14))
            oversold = float(self.params.get('oversold', 30.0))
            overbought = float(self.params.get('overbought', 70.0))
            action, meta = evaluate_rsi_extreme(series, period, oversold, overbought)
        else:
            return None

        # If action is actionable and differs from the last position signal
        if action in ('BUY', 'SELL') and action != self.last_action:
            self.last_action = action
            self.last_signal_time = now
            return Signal(
                strategy_id=self.strategy_id,
                instrument_id=self.instrument_id,
                action=action,
                price=current_price,
                timestamp=now,
                indicator_type=self.strategy_type,
                metadata=meta
            )

        return None
