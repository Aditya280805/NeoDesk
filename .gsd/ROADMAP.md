# ROADMAP.md

> **Current Milestone**: v3.0 (Automated Strategy Engine & Live Order Execution)
> **Goal**: Enable automated algorithmic trading with user-configurable strategies, real-time signal generation, and safe execution routing across Paper and Live Kotak Neo accounts with risk guardrails.

## Must-Haves
- [ ] Strategy Engine backend supporting multi-strategy runtime, parameter validation, and tick/bar signal evaluation.
- [ ] Live Kotak Neo order placement & cancellation service with strict safety checks (circuit limits, quantity limits, mode confirmation).
- [ ] Automated paper vs. live execution bridge with persistent order logs and trade audit trail.
- [ ] Strategy Lab frontend interface to configure, backtest, deploy, pause, and monitor running strategies in real time.

## Phases

### Phase 1: Strategy Engine Core & Signal Generation
**Status**: ⬜ Not Started
**Objective**: Build and test the strategy execution engine capable of evaluating algorithmic indicators (moving average crossover, RSI overbought/oversold, custom thresholds) on streaming prices and firing BUY/SELL signals.

### Phase 2: Broker Order Execution & Safety Safeguards
**Status**: ⬜ Not Started
**Objective**: Implement real Kotak Neo order execution routing with safety guardrails (max trade loss, order value caps, double-confirmation for live trades, exception fallbacks to paper trading).

### Phase 3: Strategy Lab UI & Active Management Dashboard
**Status**: ⬜ Not Started
**Objective**: Build frontend views in `/strategies/` to configure strategy parameters, trigger historical backtests, activate/pause automated bots, and display execution performance and live signal alerts.

### Phase 4: End-to-End Simulation & Verification
**Status**: ⬜ Not Started
**Objective**: Validate end-to-end strategy lifecycle from signal trigger to order fill, verify audit trails in both paper and live modes, and ensure zero unhandled execution errors.
