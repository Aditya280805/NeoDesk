---
phase: 2
plan: 2
wave: 2
---

# Plan 2.2: Live vs. Paper UI Toggle & Integration

## Objective
Implement a rock-solid Live vs. Paper toggle in the React frontend. Update the `TradeTicket`, `options`, and `portfolio` pages to switch contexts safely depending on the selected mode.

## Context
- .gsd/SPEC.md
- `neo-trading-terminal/frontend/src/components/TradeTicket.tsx`
- `neo-trading-terminal/frontend/src/pages/paper.tsx` (To be refactored/renamed or split into live vs paper)

## Tasks

<task type="auto">
  <name>Global Mode Toggle in UI</name>
  <files>
    neo-trading-terminal/frontend/src/components/Layout.tsx
    neo-trading-terminal/frontend/src/pages/_app.tsx
  </files>
  <action>
    - Add a `tradingMode` state (`'PAPER' | 'LIVE'`) in a global store or context.
    - Create a distinct visual toggle (e.g., in the `topbar` or `mode-pills` in `Layout.tsx`). When toggled to `LIVE`, the UI should prominently display a warning or change styling (e.g., a red/amber accent) to denote real money is at risk.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/frontend; & npm.cmd run lint"</verify>
  <done>Global `tradingMode` is implemented and can be toggled.</done>
</task>

<task type="auto">
  <name>Route Orders Based on Mode</name>
  <files>
    neo-trading-terminal/frontend/src/components/TradeTicket.tsx
  </files>
  <action>
    - Refactor `TradeTicket.tsx` to read the global `tradingMode`.
    - Change API calls: use `/api/paper/orders` if mode is `PAPER`, and `/api/live/orders` if mode is `LIVE`.
    - Update the ticket header to clearly display the active mode (`PAPER` vs `LIVE`).
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/frontend; & npm.cmd run lint"</verify>
  <done>TradeTicket routes orders dynamically based on `tradingMode`.</done>
</task>

<task type="auto">
  <name>Positions and Orders View Refactoring</name>
  <files>
    neo-trading-terminal/frontend/src/pages/paper.tsx
    neo-trading-terminal/frontend/src/pages/trading.tsx
  </files>
  <action>
    - Rename `paper.tsx` to `trading.tsx` (and update links across the application).
    - Update `trading.tsx` to fetch positions and orders from `/api/paper` or `/api/live` depending on the global `tradingMode`.
    - Ensure active polling/refresh mechanisms fetch from the correct endpoint dynamically.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/frontend; & npm.cmd run build"</verify>
  <done>Trading dashboard renders positions for both Live and Paper based on the mode toggle.</done>
</task>

## Success Criteria
- [x] Users can visually distinguish whether they are in Live or Paper mode.
- [x] Orders placed in Paper mode do not reach Kotak Neo APIs.
- [x] Orders placed in Live mode hit the `/api/live` endpoint.
- [x] Position tracking correctly respects the selected mode.
