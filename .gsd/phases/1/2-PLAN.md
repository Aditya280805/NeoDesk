---
phase: 1
plan: 2
wave: 2
---

# Plan 1.2: Frontend WebSocket Client & Real-Time UI

## Objective
Update the React frontend to establish a WebSocket connection to the backend and consume real-time tick data to update charts, option chains, and quotes without polling.

## Context
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- `neo-trading-terminal/frontend/src/services/`
- `neo-trading-terminal/frontend/src/stores/`
- `neo-trading-terminal/frontend/src/components/`

## Tasks

<task type="auto">
  <name>WebSocket Service and Zustand Store</name>
  <files>
    neo-trading-terminal/frontend/src/services/ws.ts
    neo-trading-terminal/frontend/src/stores/marketStore.ts
  </files>
  <action>
    - Create `ws.ts` to manage the WebSocket connection to `/api/ws/stream`. Handle auto-reconnects and cleanup.
    - Create a Zustand store `marketStore.ts` that receives tick updates from `ws.ts` and holds a dictionary of live quotes (mapped by token or instrument_id).
    - Expose a hook `useLiveQuote(instrumentId)` to reactively fetch the latest price.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/frontend; & npm.cmd run lint"</verify>
  <done>WebSocket service and Zustand store are implemented and pass linting.</done>
</task>

<task type="auto">
  <name>Wire UI Components to Live Data</name>
  <files>
    neo-trading-terminal/frontend/src/components/PriceChart.tsx
    neo-trading-terminal/frontend/src/components/TradeTicket.tsx
    neo-trading-terminal/frontend/src/pages/options.tsx
  </files>
  <action>
    - Refactor `PriceChart.tsx` to subscribe to the new `marketStore`. When a new quote arrives for the current chart's instrument, update the last candle dynamically using lightweight-charts' `update()` method.
    - Refactor `TradeTicket.tsx` to display the real-time bid/ask or LTP directly from `useLiveQuote`.
    - Update `options.tsx` to highlight Option Chain rows as prices tick in real-time instead of full-page polling.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/frontend; & npm.cmd run build"</verify>
  <done>Frontend builds successfully with no TypeScript or ESLint errors.</done>
</task>

## Success Criteria
- [ ] Charts and Quotes update seamlessly without HTTP polling.
- [ ] Option Chain reacts immediately to price changes.
- [ ] The application successfully reconnects to WebSockets if the connection drops.
