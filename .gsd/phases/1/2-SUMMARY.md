# Plan 1.2 Summary: Persistent Strategy Engine & Signals API

**Status:** Completed

## Tasks Completed
1. **Added Strategies & Signals SQLite Storage Tables (`backend/app/terminal/store.py`):**
   - Added tables: `strategies` (with columns for params, mode, status, cash, held, realized_pnl, total_trades) and `signals` (with index on strategy_id and timestamp).
   - Added Store methods: `save_strategy`, `get_strategy`, `list_strategies`, `update_strategy_state`, `record_signal`, `get_signals`.
2. **Upgraded Strategy Engine with Persistence & Signal Broadcasting (`backend/app/terminal/engine.py`, `backend/app/terminal/server.py`):**
   - StrategyEngine now restores running strategies from SQLite upon instantiation.
   - Integrated `IndicatorEvaluator` for multi-algorithm evaluations (`SMA_CROSSOVER`, `EMA_CROSSOVER`, `RSI_EXTREME`).
   - Emits and stores `Signal` objects on price movements and broadcasts them across the WebSocket manager (`manager.broadcast({"type": "SIGNAL", "data": ...})`).
   - Added/expanded REST endpoints:
     - `POST /api/strategies/deploy`: Supports configurable strategy algorithms and parameters.
     - `GET /api/strategies/active`: Returns all running/stopped bots with live balance and P&L.
     - `GET /api/strategies/{sid}`: Returns specific bot configuration and stats.
     - `GET /api/strategies/{sid}/signals`: Returns historical signals for a bot.
     - `GET /api/signals/recent`: Returns recent signals across all running bots.
     - `DELETE /api/strategies/{sid}`: Stops/pauses the strategy.
3. **Integration Test Suite (`backend/tests/test_strategy_engine.py`):**
   - Tested multi-algorithm deployment and DB persistence across engine restarts.
   - Tested tick ingestion, signal emission, and paper trade execution.
   - Tested all REST API endpoints using Starlette `TestClient`.

## Verification
- All 53 backend tests pass cleanly in 5.45s.
