---
phase: 2
plan: 2
wave: 2
depends_on: [1]
---

# Plan 2.2: Live Broker Order Routing & Strategy Engine Integration

## Objective
Connect the RiskManager to both manual and automated live order execution pathways. Enable automated strategies running in `live` mode to execute orders through Kotak Neo broker client with strict pre-trade risk validation, circuit collar checks, audit logging, and emergency kill switch controls.

## Context
- .gsd/SPEC.md
- neo-trading-terminal/backend/app/terminal/risk.py
- neo-trading-terminal/backend/app/terminal/live.py
- neo-trading-terminal/backend/app/terminal/engine.py
- neo-trading-terminal/backend/app/terminal/server.py

## Tasks

<task type="auto">
  <name>Integrate Pre-Trade Risk Checks into Live Router & Add Risk Endpoints</name>
  <files>neo-trading-terminal/backend/app/terminal/live.py, neo-trading-terminal/backend/app/terminal/server.py</files>
  <action>
    1. Update `neo-trading-terminal/backend/app/terminal/live.py`:
       - Before placing manual live orders in `POST /live/orders`, validate order through `request.app.state.risk_manager.validate_order(...)`.
       - Catch `RiskViolationError` and return HTTP 400 with detailed violation reason.
       - Log audit event in `store.audit('live_order_submitted', ...)` on success or rejection.
    2. Add Risk API endpoints in `neo-trading-terminal/backend/app/terminal/server.py`:
       - Attach `risk_manager` to `app.state.risk_manager`.
       - `GET /api/risk/status`: returns kill switch status, current daily loss, and configured limits.
       - `POST /api/risk/kill-switch`: triggers emergency kill switch, logs audit event.
       - `POST /api/risk/reset-kill-switch`: resets kill switch with confirmation check.
       - `PUT /api/risk/limits`: updates risk limit parameters (max_order_value, max_daily_loss, etc.).
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -c "from app.terminal.server import create_app; from app.core.config import Settings; app = create_app(Settings()); print('app created with risk_manager')"</verify>
  <done>Manual live orders are gated by pre-trade risk validation and risk control endpoints are functional.</done>
</task>

<task type="auto">
  <name>Wire Live Order Routing and Risk Validation into StrategyEngine</name>
  <files>neo-trading-terminal/backend/app/terminal/engine.py</files>
  <action>
    Update `neo-trading-terminal/backend/app/terminal/engine.py`:
    1. Inject or accept `risk_manager` into `StrategyEngine.__init__(self, store, market, paper, risk_manager=None)`.
    2. In `_execute_order(strat, instrument, side, quantity, price)`:
       - If `strat['mode'] == 'live'`:
         * Run `self.risk_manager.validate_order(instrument, side, quantity, price, ltp=price)`.
         * If validation fails (`RiskViolationError`), log warning, record audit event, broadcast alert over WebSocket (`{"type": "RISK_ALERT", "data": ...}`), and return without sending order.
         * If validation passes, route order via `self.market.broker.client.place_order(...)`.
         * Handle broker exceptions gracefully (OrderError, RateLimitError, etc.) without halting the bot loop.
         * Record placed live order in SQLite `orders` table with status `SUBMITTED`.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_live_execution.py -v</verify>
  <done>StrategyEngine safely executes live orders through broker client only after passing risk checks.</done>
</task>

<task type="auto">
  <name>Create Live Order Execution & Risk Integration Test Suite</name>
  <files>neo-trading-terminal/backend/tests/test_live_execution.py</files>
  <action>
    Create `neo-trading-terminal/backend/tests/test_live_execution.py`:
    1. Test manual live order blocked when order value exceeds max limit.
    2. Test manual live order blocked when emergency kill switch is active.
    3. Test automated strategy live order execution:
       - Mock broker client order placement.
       - Verify order is validated by RiskManager before calling broker.
       - Verify order is blocked and alert emitted if kill switch is triggered.
    4. Test risk endpoints (`/api/risk/status`, `/api/risk/kill-switch`, `/api/risk/reset-kill-switch`).
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_live_execution.py -v</verify>
  <done>All integration tests in test_live_execution.py pass with 100% assertions.</done>
</task>

## Success Criteria
- [ ] Manual and automated live orders cannot bypass pre-trade risk validation.
- [ ] Automated live orders route to Kotak Neo SDK with safety and audit logging.
- [ ] Emergency kill switch stops all live orders instantly across manual and automated channels.
- [ ] Complete test suite passes cleanly.
