# SPEC.md — Project Specification

> **Status**: `FINALIZED`

## Vision
To evolve NeoDesk into a smooth, production-grade, real-time trading terminal for the Indian market. It will provide a seamless live-streaming dashboard with WebSocket integration, automated algorithmic strategy execution, and safe toggling between real-money live F&O/Equity trading (via Kotak Neo) and simulated paper trading.

## Goals
1. **Real-Time Data Streaming:** Transition from REST polling to WebSockets for live, tick-by-tick quotes, option chains, and order status updates.
2. **Live Trading & Order Routing:** Safely enable F&O and equity real-money execution via the Kotak Neo API, featuring a strict "Live vs. Paper" mode toggle to prevent accidental trades.
3. **Automated Algorithmic Execution:** Build an engine to not only backtest but automatically execute user-defined trading strategies.
4. **UI/UX Overhaul:** Refine and smooth out the dashboard, focusing on high-performance charts, an intuitive option chain, and a streamlined order ticket experience.

## Non-Goals (Out of Scope)
- Multi-user authentication (designed for single-user personal hosting).
- Trading on exchanges outside of NSE/BSE.

## Users
Single-user algorithmic and manual trader managing their own Kotak Neo account, requiring high-speed data and automated execution capabilities.

## Constraints
- Must safely isolate Live and Paper trading states without data corruption.
- Real-time data streaming is subject to Kotak Neo API limits and WebSocket stability.
- UI must remain performant when processing high-frequency tick data.

## Success Criteria
- [ ] WebSocket feed successfully updates UI components (charts, quotes, option chain) without noticeable lag.
- [ ] Real-money orders can be reliably placed, modified, and cancelled via the Kotak API.
- [ ] A custom strategy can automatically trigger a trade in the live or paper environment based on real-time signals.
- [ ] UI is perceptibly smoother, with improved visual polish and responsiveness across core components.
