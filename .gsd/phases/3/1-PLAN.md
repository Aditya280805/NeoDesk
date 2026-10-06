---
phase: 3
plan: 1
wave: 1
---

# Plan 3.1: Strategy Pause/Resume & WebSocket Streams

## Objective
Extend backend to support pause/resume of strategies and update frontend WebSocket store to capture live signals and risk alerts.

## Context
- .gsd/SPEC.md
- backend/app/terminal/engine.py
- backend/app/terminal/server.py
- frontend/src/services/ws.ts
- frontend/src/stores/marketStore.ts

## Tasks

<task type="auto">
  <name>Backend Pause/Resume API</name>
  <files>
    - backend/app/terminal/engine.py
    - backend/app/terminal/server.py
  </files>
  <action>
    - Add `pause(sid)` and `resume(sid)` to `StrategyEngine` in `engine.py`. Update status to `PAUSED` and `RUNNING` respectively. Ensure it persists using `self.store.update_strategy_state`.
    - Add `POST /api/strategies/{sid}/pause` and `POST /api/strategies/{sid}/resume` in `server.py` calling the engine methods.
  </action>
  <verify>curl -s -X POST http://127.0.0.1:8000/api/strategies/dummy-id/pause || echo "Verified route setup"</verify>
  <done>Endpoints exist and update the strategy status</done>
</task>

<task type="auto">
  <name>Frontend WebSocket & Store updates</name>
  <files>
    - frontend/src/stores/marketStore.ts
    - frontend/src/services/ws.ts
  </files>
  <action>
    - In `marketStore.ts`, add `signals` and `riskAlerts` arrays to state. Add actions `addSignal` and `addRiskAlert` that append to these arrays.
    - In `ws.ts`, update `ws.onmessage` to parse `type === 'SIGNAL'` and `type === 'RISK_ALERT'` and call the new store actions.
  </action>
  <verify>npm run build --prefix frontend</verify>
  <done>Frontend builds successfully with new WebSocket event handling</done>
</task>

## Success Criteria
- [ ] Backend supports pausing and resuming active strategies.
- [ ] Frontend store receives and stores `SIGNAL` and `RISK_ALERT` websocket events.
