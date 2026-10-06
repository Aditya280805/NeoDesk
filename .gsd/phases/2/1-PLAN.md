---
phase: 2
plan: 1
wave: 1
depends_on: []
---

# Plan 2.1: Risk Guardrails & Safety Controls Engine

## Objective
Establish a dedicated risk management layer (`risk.py`) that enforces non-negotiable safety guardrails before any live capital can be committed: order value caps, price collar / fat-finger filters, daily loss limit tracking, and an emergency kill switch.

## Context
- .gsd/SPEC.md
- neo-trading-terminal/backend/app/terminal/store.py
- neo-trading-terminal/backend/app/terminal/live.py

## Tasks

<task type="auto">
  <name>Implement RiskManager with Guardrails and Kill Switch</name>
  <files>neo-trading-terminal/backend/app/terminal/risk.py</files>
  <action>
    Create `neo-trading-terminal/backend/app/terminal/risk.py`:
    1. Define custom exceptions:
       - `RiskViolationError(message: str, code: str)`
    2. Define `RiskLimits` dataclass/Pydantic model:
       - `max_order_value`: float (default 500000.0)
       - `max_daily_loss`: float (default 25000.0)
       - `max_price_deviation_pct`: float (default 10.0)
       - `max_quantity_per_order`: int (default 10000)
    3. Implement `RiskManager` class:
       - Methods:
         - `validate_order(instrument, side, quantity, price, ltp)`:
           * Verifies kill switch is NOT active.
           * Verifies order value (`quantity * (price or ltp)`) <= `max_order_value`.
           * Verifies price deviation: if limit price provided, checks `abs(price - ltp) / ltp * 100 <= max_price_deviation_pct`.
           * Verifies daily accumulated loss <= `max_daily_loss`.
         - `trigger_kill_switch(reason: str)`: disables all live trading orders immediately.
         - `reset_kill_switch()`: re-enables trading after operator review.
         - `record_trade_pnl(realized_pnl: float)`: updates daily loss counter.
         - `get_status() -> dict`: returns kill switch state, daily loss, limits, and risk metrics.
    Avoid allowing live trades when any limit is violated.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -c "from app.terminal.risk import RiskManager, RiskViolationError; rm = RiskManager(); print('risk module importable')"</verify>
  <done>RiskManager cleanly validates order sizes, price collars, daily loss thresholds, and kill switch state.</done>
</task>

<task type="auto">
  <name>Create Risk Guardrails Unit Test Suite</name>
  <files>neo-trading-terminal/backend/tests/test_risk.py</files>
  <action>
    Create `neo-trading-terminal/backend/tests/test_risk.py`:
    1. Test order value cap violation: reject order exceeding max order value.
    2. Test price collar violation: reject order with limit price deviating > 10% from LTP.
    3. Test daily max loss gate: record losses up to threshold, verify subsequent orders are blocked.
    4. Test emergency kill switch: trigger kill switch, verify all orders are immediately rejected, reset kill switch, verify orders resume.
    5. Test quantity limits: reject orders with invalid or excessive quantities.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_risk.py -v</verify>
  <done>All tests in test_risk.py pass with 100% assertions covering all guardrail rules and edge cases.</done>
</task>

## Success Criteria
- [ ] RiskManager correctly intercepts and blocks excessive order values, price deviations, and breached loss limits.
- [ ] Emergency kill switch immediately stops all live order authorizations.
- [ ] Test suite covers all guardrails with full assertions.
