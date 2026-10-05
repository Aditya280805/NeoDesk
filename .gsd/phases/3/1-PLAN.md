---
phase: 3
plan: 1
wave: 1
---

# Plan 3.1: Strategy Engine Core & API

## Objective
Build a background execution engine that can evaluate real-time signals (e.g., tick data) and trigger trades autonomously. We will expose APIs to start, stop, and list running strategies, linking them to either the Paper or Live execution modes based on the current context.

## Context
- .gsd/SPEC.md
- app/terminal/analytics.py
- app/terminal/server.py

## Tasks

<task type="auto">
  <name>Strategy Engine Implementation</name>
  <files>
    - backend/app/terminal/engine.py
    - backend/app/terminal/server.py
  </files>
  <action>
    - Create `engine.py` with an async `StrategyRunner` class.
    - It should maintain a list of active strategies (e.g., SMA crossover instances) with configuration parameters (instrument, fast SMA, slow SMA, mode).
    - Expose methods to `start(config)`, `stop(id)`, and `list_active()`.
    - Hook the `StrategyRunner` into the `server.py` lifespan (similar to `match_loop` or `sfeed_loop`), giving it access to real-time `manager` broadcasts or direct feed data to update internal indicators and trigger `BUY`/`SELL` orders via the paper or live router.
  </action>
  <verify>curl -X GET http://localhost:8000/api/strategies/active (should return empty list)</verify>
  <done>The engine loop is implemented and running without crashing the FastAPI app.</done>
</task>

<task type="auto">
  <name>Engine API Endpoints</name>
  <files>
    - backend/app/terminal/server.py
  </files>
  <action>
    - Add `POST /api/strategies/deploy` to instantiate a live runner instance for a given instrument and mode (Paper or Live).
    - Add `GET /api/strategies/active` to list currently running strategies.
    - Add `DELETE /api/strategies/{id}` to terminate an active strategy.
  </action>
  <verify>curl -X POST http://localhost:8000/api/strategies/deploy -d '{"instrument_id": "1", "mode": "paper", ...}'</verify>
  <done>Deploying and stopping a strategy successfully tracks it in the backend engine.</done>
</task>

## Success Criteria
- [ ] Strategy runner successfully runs in the background.
- [ ] New APIs correctly start, list, and stop active strategy instances.
- [ ] The engine correctly evaluates simple conditions based on incoming ticks/history.
