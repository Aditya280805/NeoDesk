---
phase: 4
plan: 1
wave: 1
gap_closure: false
depends_on: []
---

# Plan 4.1: End-to-End Simulation & Verification

## Objective
Validate the complete strategy lifecycle from signal generation to order execution and audit logging across both Paper and Live modes, ensuring zero unhandled exceptions and solid guardrail integration.

## Context
Load these files for context:
- .gsd/ROADMAP.md
- neo-trading-terminal/backend/app/terminal/engine.py
- neo-trading-terminal/backend/app/terminal/store.py
- neo-trading-terminal/backend/tests/test_strategy_engine.py
- neo-trading-terminal/backend/tests/test_live_execution.py

## Tasks

<task type="auto">
  <name>Implement Paper Mode E2E Simulation Test</name>
  <files>neo-trading-terminal/backend/tests/test_e2e.py</files>
  <action>
    Create a new test file `test_e2e.py`.
    Implement `test_e2e_paper_lifecycle` that:
    1. Initializes Market, PaperAccount, Store, and StrategyEngine (using `test_setup` fixture style).
    2. Deploys a strategy (e.g. SMA_CROSSOVER) in 'paper' mode.
    3. Feeds a predefined sequence of mock ticks via `engine.on_tick` designed to trigger at least one BUY and one SELL signal.
    4. Asserts that the signals were generated, paper orders were placed and transitioned to FILLED, strategy position (`held`) updated correctly, and audit logs were recorded.
    
    AVOID: Relying on network calls.
    USE: In-memory/SQLite store and mock data.
  </action>
  <verify>
    pytest neo-trading-terminal/backend/tests/test_e2e.py::test_e2e_paper_lifecycle -v
  </verify>
  <done>
    Test passes, successfully simulating a complete trade lifecycle in paper mode with validated state.
  </done>
</task>

<task type="auto">
  <name>Implement Live Mode Guardrail E2E Test</name>
  <files>neo-trading-terminal/backend/tests/test_e2e.py</files>
  <action>
    Implement `test_e2e_live_guardrails_lifecycle` in `test_e2e.py` that:
    1. Initializes engine with a mock Live Kotak execution client.
    2. Deploys a strategy in 'live' mode.
    3. Simulates ticks that trigger signals but intentionally configures the environment/mock to trip safety guardrails (e.g. mock Kotak API exception or circuit limit breach).
    4. Asserts that the engine gracefully handles the rejection/exception during `_execute_order`, records the failure in the audit log or signal state, and preserves the strategy position state accurately (it shouldn't think it holds position if order failed).
    
    AVOID: Unhandled exceptions crashing the engine test.
    USE: Pytest-mock (`mocker.patch`) for the Live execution API to force failure scenarios.
  </action>
  <verify>
    pytest neo-trading-terminal/backend/tests/test_e2e.py::test_e2e_live_guardrails_lifecycle -v
  </verify>
  <done>
    Test passes, demonstrating live mode safely traps errors, rejects invalid orders, and correctly logs failures without crashing.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] End-to-end lifecycle runs without unhandled errors for Paper mode.
- [ ] Live mode gracefully catches API/guardrail errors and logs them.
- [ ] Audit trails (store logic) are successfully verified in E2E tests.

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
