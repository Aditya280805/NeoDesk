# ROADMAP.md

> **Current Phase**: Phase 2
> **Milestone**: v1.0 (Live Streaming & Trading Integration)

## Must-Haves (from SPEC)
- [x] WebSocket streaming for market data and order status.
- [x] Live F&O and Equity trading integration.
- [x] Live vs. Paper mode toggle.
- [ ] Automated strategy execution engine.
- [ ] UI/UX refinement.

## Phases

### Phase 1: Real-Time Infrastructure (WebSockets)
**Status**: ✅ Completed
**Objective**: Replace REST polling with live WebSocket streaming for quotes, charts, and option chains.
**Requirements**: REQ-01, REQ-06

### Phase 2: Live Trading Engine & State Isolation
**Status**: ✅ Completed
**Objective**: Implement real-money order routing to Kotak Neo, and build a rock-solid Live vs. Paper toggle system to ensure safety.
**Requirements**: REQ-02, REQ-03, REQ-04, REQ-07

### Phase 3: Automated Strategy Execution
**Status**: ⬜ Not Started
**Objective**: Upgrade the current backtesting framework to support live execution of algorithmic strategies based on real-time signals.
**Requirements**: REQ-05

### Phase 4: UI Polish & Dashboard Refinement
**Status**: ⬜ Not Started
**Objective**: Overhaul the visual aesthetics, smooth out interactive components (Order Ticket, Option Chain), and optimize rendering for high-frequency data.
**Requirements**: REQ-06
