---
phase: 3
plan: 2
wave: 2
---

# Plan 3.2: UI Integration for Strategy Deployment

## Objective
Update the frontend to interact with the backend strategy engine. Users should be able to transition from backtesting to live deployment directly from the `strategies.tsx` lab, and monitor active strategies.

## Context
- .gsd/SPEC.md
- frontend/src/pages/strategies.tsx
- frontend/src/components/Layout.tsx

## Tasks

<task type="auto">
  <name>Strategy Deployment UI</name>
  <files>
    - frontend/src/pages/strategies.tsx
  </files>
  <action>
    - Add a new "Deploy Strategy" button next to "Run Backtest".
    - The button should respect `tradingMode` (Live/Paper) from `marketStore` and send the deployment request to `POST /api/strategies/deploy`.
    - Show a list of "Active Strategies" at the bottom or top of the page, fetching from `GET /api/strategies/active`.
    - Provide a "Stop" button for each active strategy.
  </action>
  <verify>npm run lint</verify>
  <done>Users can deploy, view, and stop active strategies from the frontend UI.</done>
</task>

## Success Criteria
- [ ] UI clearly displays currently running strategies.
- [ ] Users can deploy strategies into Live or Paper mode depending on their UI toggle state.
- [ ] Stopping a strategy reflects immediately in the UI.
