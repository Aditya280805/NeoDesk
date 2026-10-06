---
phase: 1
plan: 2
wave: 2
depends_on: [1]
---

# Plan 1.2: Persistent Strategy Engine & Signals API

## Objective
Upgrade the backend Strategy Engine to persist configured strategies and generated signals in SQLite. Allow the engine to run multiple strategy algorithms (SMA, EMA, RSI) simultaneously on real-time ticks, record signals to the database, stream signal alerts across WebSockets, and expose full REST APIs for strategy monitoring.

## Context
- .gsd/SPEC.md
- neo-trading-terminal/backend/app/terminal/store.py
- neo-trading-terminal/backend/app/terminal/engine.py
- neo-trading-terminal/backend/app/terminal/server.py
- neo-trading-terminal/backend/app/terminal/signals.py

## Tasks

<task type="auto">
  <name>Add Strategies & Signals SQLite Storage Tables</name>
  <files>neo-trading-terminal/backend/app/terminal/store.py</files>
  <action>
    Update `neo-trading-terminal/backend/app/terminal/store.py`:
    1. In the database initialization SQL, add `strategies` and `signals` tables:
       - `strategies(id TEXT PRIMARY KEY, name TEXT, strategy_type TEXT, instrument_id TEXT, params TEXT, mode TEXT, status TEXT, created_at REAL, updated_at REAL, cash REAL, held INTEGER, realized_pnl REAL, total_trades INTEGER)`
       - `signals(id TEXT PRIMARY KEY, strategy_id TEXT, instrument_id TEXT, action TEXT, price REAL, indicator_type TEXT, metadata TEXT, timestamp REAL, order_id TEXT)`
       - Add index on `signals(strategy_id, timestamp)` and `strategies(status)`.
    2. Add store helper methods:
       - `save_strategy(strategy_dict)`: inserts or updates strategy row.
       - `get_strategy(sid)`: retrieves single strategy.
       - `list_strategies(status=None)`: returns all active/stopped strategies.
       - `update_strategy_state(sid, cash, held, realized_pnl, total_trades, status)`: updates execution state.
       - `record_signal(signal)`: stores generated signal in the `signals` table.
       - `get_signals(strategy_id=None, limit=50)`: retrieves recent signals.
  </action>
  <verify>python.exe -c "from app.terminal.store import Store; from pathlib import Path; s = Store(Path('test_store.sqlite3'), 100000); print('store schemas verified')" ; rm test_store.sqlite3*</verify>
  <done>SQLite schema contains strategies and signals tables with robust CRUD methods for persistence.</done>
</task>

<task type="auto">
  <name>Upgrade Strategy Engine with Multi-Strategy Support, DB Persistence & Signal Broadcasting</name>
  <files>neo-trading-terminal/backend/app/terminal/engine.py, neo-trading-terminal/backend/app/terminal/server.py</files>
  <action>
    1. Upgrade `neo-trading-terminal/backend/app/terminal/engine.py`:
       - On `__init__`, load running strategies from `store.list_strategies(status='RUNNING')` into memory.
       - In `deploy(...)`, support `strategy_type` ('SMA_CROSSOVER', 'EMA_CROSSOVER', 'RSI_EXTREME') and strategy parameters dict `params`. Save to DB immediately.
       - In `on_tick(...)`, evaluate the corresponding signal evaluator from `signals.py`.
       - When a signal is generated, save it using `store.record_signal(...)` and broadcast over WebSocket manager via `manager.broadcast({"type": "SIGNAL", "data": signal.to_dict()})`.
       - In `stop(sid)` and `remove(sid)`, update the database status to 'STOPPED' or delete the record.
    2. Update endpoints in `neo-trading-terminal/backend/app/terminal/server.py`:
       - `POST /api/strategies/deploy`: Accept `strategy_type`, `name`, `instrument_id`, `params`, `initial`, `mode`. Return created strategy.
       - `GET /api/strategies/active`: Return all strategies from DB with live status, PnL, and positions.
       - `GET /api/strategies/{sid}/signals`: Return recent signal history for a specific strategy.
       - `GET /api/signals/recent`: Return global recent signals across all active strategies.
       - `DELETE /api/strategies/{sid}`: Pause/stop the strategy.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_strategy_engine.py -v</verify>
  <done>Engine seamlessly manages multi-algorithm strategies, survives server restarts via DB persistence, and broadcasts live signals.</done>
</task>

<task type="auto">
  <name>Add Integration Test Suite for Strategy Engine & Signals API</name>
  <files>neo-trading-terminal/backend/tests/test_strategy_engine.py</files>
  <action>
    Create `neo-trading-terminal/backend/tests/test_strategy_engine.py`:
    1. Test deploying multiple strategy types (SMA, EMA, RSI) via StrategyEngine.
    2. Test that deployed strategies survive engine restart (create new StrategyEngine instance and verify state is restored).
    3. Test tick ingestion generating signals and persisting to SQLite `signals` table.
    4. Test REST API endpoints:
       - Deploy strategy endpoint.
       - Active strategies list endpoint.
       - Signal history endpoint.
       - Stop strategy endpoint.
  </action>
  <verify>& ".\.venv\Scripts\python.exe" -m pytest tests/test_strategy_engine.py -v</verify>
  <done>All integration tests pass verifying end-to-end strategy lifecycle, signal recording, and API endpoints.</done>
</task>

## Success Criteria
- [ ] Strategy configurations and states persist across server restarts.
- [ ] Multi-indicator algorithms evaluate live ticks and record signal logs.
- [ ] WebSocket broadcasts live `SIGNAL` events on triggers.
- [ ] Integration tests pass cleanly.
