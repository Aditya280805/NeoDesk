---
phase: 3
plan: 2
wave: 2
---

# Plan 3.2: Strategy Lab UI & Risk Dashboard

## Objective
Integrate Pause/Resume and WebSocket feeds into `strategies.tsx` and build the Risk Guardrails UI in `Layout.tsx` and `trading.tsx`.

## Context
- .gsd/SPEC.md
- frontend/src/pages/strategies.tsx
- frontend/src/components/Layout.tsx
- frontend/src/pages/trading.tsx

## Tasks

<task type="auto">
  <name>Strategy Lab UI updates</name>
  <files>
    - frontend/src/pages/strategies.tsx
  </files>
  <action>
    - Add "Pause" and "Resume" buttons to the Active Deployments table, calling the new backend endpoints.
    - Display a "Live Feed" section that maps over `signals` and `riskAlerts` from `marketStore`.
    - Show P&L and total trades for running strategies in the table.
  </action>
  <verify>npm run build --prefix frontend</verify>
  <done>Strategy Lab displays real-time feed and supports pause/resume</done>
</task>

<task type="auto">
  <name>Global Kill Switch & Risk Dashboard</name>
  <files>
    - frontend/src/components/Layout.tsx
    - frontend/src/pages/trading.tsx
  </files>
  <action>
    - In `Layout.tsx`, add a red "KILL SWITCH" button in the Topbar when `tradingMode === 'LIVE'`. Clicking it triggers `POST /api/risk/kill-switch`.
    - In `trading.tsx`, add a "Risk Guardrails" section that fetches `/api/risk/status`. Allow editing limits via `PUT /api/risk/limits` and resetting kill switch via `POST /api/risk/reset-kill-switch`.
  </action>
  <verify>npm run build --prefix frontend</verify>
  <done>Kill Switch accessible globally in Live mode, and Risk Limits configurable</done>
</task>

## Success Criteria
- [ ] Active algorithms can be paused and resumed via the UI.
- [ ] Live signals and risk alerts appear in the Strategy Lab real-time feed.
- [ ] Global Kill Switch is visible in the topbar during Live mode.
