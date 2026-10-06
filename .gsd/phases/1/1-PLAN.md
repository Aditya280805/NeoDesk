---
phase: 1
plan: 1
wave: 1
depends_on: []
---

# Plan 1.1: Strategy Indicator Evaluator & Signal System

## Objective
Establish a modular algorithmic signal generation layer (`signals.py`) supporting multiple technical indicators (SMA Crossover, EMA Crossover, RSI Overbought/Oversold). Ensure signal triggers emit standardized `Signal` events with full mathematical validation and debouncing to prevent high-frequency noise.

## Context
- .gsd/SPEC.md
- backend/app/terminal/analytics.py
- backend/app/terminal/engine.py

## Tasks

<task type="auto">
  <name>Implement Technical Signal Evaluators and Signal Models</name>
  <files>neo-trading-terminal/backend/app/terminal/signals.py</files>
  <action>
    Create `neo-trading-terminal/backend/app/terminal/signals.py`:
    1. Define `SignalAction` ('BUY', 'SELL', 'HOLD') and `Signal` dataclass/Pydantic model containing:
       - `strategy_id`: str
       - `instrument_id`: str
       - `action`: SignalAction
       - `price`: float
       - `timestamp`: float
       - `indicator_type`: str ('SMA_CROSSOVER', 'EMA_CROSSOVER', 'RSI_EXTREME')
       - `metadata`: dict (e.g., indicator values, fast/slow readings)
    2. Implement mathematical indicator signal evaluators:
       - `evaluate_sma_crossover(closes, fast, slow)`: detects golden cross (BUY) and death cross (SELL) across preceding candle closes.
       - `evaluate_ema_crossover(closes, fast, slow)`: computes exponential moving averages with smoothing factor `2 / (period + 1)` and detects crossovers.
       - `evaluate_rsi_extreme(closes, period=14, oversold=30, overbought=70)`: triggers BUY when RSI dips below oversold and rebounds, and SELL when RSI exceeds overbought.
    3. Include debouncing and state tracking in an `IndicatorEvaluator` wrapper to prevent duplicate signals on consecutive ticks at the same price bar.
    Avoid coupling signal calculation directly to order submission or broker network calls.
  </action>
  <verify>python.exe -c "from app.terminal.signals import Signal, evaluate_sma_crossover, evaluate_ema_crossover, evaluate_rsi_extreme; print('signals module importable')"</verify>
  <done>Signals module cleanly calculates indicators and emits valid typed Signal instances without errors.</done>
</task>

<task type="auto">
  <name>Create Unit Test Suite for Signal Evaluators</name>
  <files>neo-trading-terminal/backend/tests/test_signals.py</files>
  <action>
    Create `neo-trading-terminal/backend/tests/test_signals.py`:
    1. Test SMA Crossover with synthetic upward price series (verify BUY signal) and downward series (verify SELL signal).
    2. Test EMA Crossover responsiveness compared to SMA.
    3. Test RSI Overbought/Oversold thresholds with oscillation data.
    4. Test edge cases: insufficient price history (< slow period), constant/flat prices (zero variance), and missing data handling.
    5. Test debouncing logic: ensure repeated identical prices within the same bar do not trigger repeated thrashing signals.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_signals.py -v</verify>
  <done>All tests in test_signals.py pass with 100% assertions covering all indicator evaluators and edge cases.</done>
</task>

## Success Criteria
- [ ] Technical indicators (SMA, EMA, RSI) evaluate correctly and emit standardized `Signal` objects.
- [ ] Edge cases (short series, zero movement, debouncing) are guarded.
- [ ] Full pytest test suite for signals passes cleanly.
