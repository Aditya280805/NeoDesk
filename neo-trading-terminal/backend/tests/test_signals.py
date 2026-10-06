import pytest
from app.terminal.signals import (
    Signal,
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    evaluate_sma_crossover,
    evaluate_ema_crossover,
    evaluate_rsi_extreme,
    IndicatorEvaluator
)

def test_calculate_sma():
    assert calculate_sma([], 5) is None
    assert calculate_sma([1, 2, 3], 5) is None
    series = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calculate_sma(series, 3) == 40.0
    assert calculate_sma(series, 5) == 30.0

def test_calculate_ema():
    assert calculate_ema([], 5) is None
    series = [10.0, 10.0, 10.0, 10.0, 10.0]
    assert calculate_ema(series, 3) == 10.0
    # On rising series, EMA gives higher weight to recent prices
    rising = [10.0, 12.0, 14.0, 16.0, 25.0]
    ema_val = calculate_ema(rising, 3)
    sma_val = calculate_sma(rising, 3)
    assert ema_val > sma_val

def test_calculate_rsi():
    assert calculate_rsi([], 14) is None
    assert calculate_rsi([10.0] * 10, 14) is None
    # 20 flat prices -> RSI is 50
    flat = [100.0] * 20
    assert calculate_rsi(flat, 14) == 50.0
    # Strongly upward prices -> RSI should be high (> 70)
    upward = [100.0 + i * 2.0 for i in range(25)]
    assert calculate_rsi(upward, 14) > 70.0
    # Strongly downward prices -> RSI should be low (< 30)
    downward = [200.0 - i * 2.0 for i in range(25)]
    assert calculate_rsi(downward, 14) < 30.0

def test_evaluate_sma_crossover_signals():
    # Insufficient history
    action, meta = evaluate_sma_crossover([10.0, 11.0], 5, 10)
    assert action == 'HOLD'
    assert 'Insufficient history' in meta['reason']

    # Downward then sharp upward -> Golden Cross (BUY)
    base = [100.0 - i * 0.5 for i in range(15)]
    surge = base + [110.0]
    action, meta = evaluate_sma_crossover(surge, fast=3, slow=10)
    assert action == 'BUY'
    assert meta['curr_fast'] > meta['curr_slow']

    # Upward then sharp collapse -> Death Cross (SELL)
    bull = [100.0 + i * 1.0 for i in range(15)]
    crash = bull + [70.0]
    action, meta = evaluate_sma_crossover(crash, fast=3, slow=10)
    assert action == 'SELL'
    assert meta['curr_fast'] < meta['curr_slow']

def test_evaluate_ema_crossover():
    base = [50.0 - i * 0.2 for i in range(15)]
    surge = base + [75.0]
    action, meta = evaluate_ema_crossover(surge, fast=3, slow=10)
    assert action == 'BUY'

def test_evaluate_rsi_extreme():
    # Oversold series (< 30)
    oversold_series = [150.0 - i * 3.0 for i in range(25)]
    action, meta = evaluate_rsi_extreme(oversold_series, period=14, oversold=30.0, overbought=70.0)
    assert action == 'BUY'
    assert meta['curr_rsi'] < 30.0

    # Overbought series (> 70)
    overbought_series = [50.0 + i * 3.0 for i in range(25)]
    action, meta = evaluate_rsi_extreme(overbought_series, period=14, oversold=30.0, overbought=70.0)
    assert action == 'SELL'
    assert meta['curr_rsi'] > 70.0

def test_indicator_evaluator_debouncing():
    evaluator = IndicatorEvaluator(
        strategy_id='strat-1',
        instrument_id='NSE:RELIANCE',
        strategy_type='SMA_CROSSOVER',
        params={'fast': 3, 'slow': 5, 'cooldown_seconds': 0.0}
    )
    
    # Send prices leading to golden cross
    history = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
    # First spike triggers BUY
    sig1 = evaluator.evaluate(history, 120.0)
    assert sig1 is not None
    assert sig1.action == 'BUY'
    assert sig1.strategy_id == 'strat-1'
    assert sig1.price == 120.0

    # Next tick with same bullish condition should NOT duplicate BUY signal
    sig2 = evaluator.evaluate(history + [120.0], 121.0)
    assert sig2 is None

    # First plunge tick that triggers crossover to SELL
    sig3 = evaluator.evaluate(history + [120.0, 121.0, 80.0], 60.0)
    assert sig3 is not None
    assert sig3.action == 'SELL'
