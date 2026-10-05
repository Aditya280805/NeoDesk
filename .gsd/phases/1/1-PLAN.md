---
phase: 1
plan: 1
wave: 1
---

# Plan 1.1: Backend WebSocket Manager & SDK Integration

## Objective
Establish WebSocket infrastructure on the backend to consume live data from the Kotak Neo SDK and broadcast it to connected frontend clients.

## Context
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/1/RESEARCH.md
- `neo-trading-terminal/backend/app/websocket/` (empty dir placeholder)
- `neo-trading-terminal/backend/app/terminal/server.py`

## Tasks

<task type="auto">
  <name>WebSocket Manager implementation</name>
  <files>neo-trading-terminal/backend/app/websocket/manager.py</files>
  <action>
    Implement a `ConnectionManager` class in `manager.py`.
    - It should accept, disconnect, and maintain a list of active websocket connections.
    - Add an async method `broadcast(message: dict)` to send JSON messages to all connected clients.
  </action>
  <verify>powershell -Command "if (!(Test-Path neo-trading-terminal/backend/app/websocket/manager.py)) { exit 1 }"</verify>
  <done>ConnectionManager class exists with connect, disconnect, and broadcast methods.</done>
</task>

<task type="auto">
  <name>Kotak SDK SFeed Integration & API Route</name>
  <files>neo-trading-terminal/backend/app/terminal/server.py</files>
  <action>
    - Add a WebSocket route `/api/ws/stream` in `server.py` that upgrades the connection, authenticates using the existing session token, and adds the client to the `ConnectionManager`.
    - Inside `server.py`'s lifespan manager, spawn a background task when `market.broker.is_authenticated` becomes true that connects to Kotak's `SFeed` via `market.broker.client.create_websocket()`.
    - Listen for `SFeedScrip` messages and broadcast them through the `ConnectionManager` to frontend clients as JSON (e.g. `{"type": "QUOTE", "data": {"token": token, "ltp": ltp}}`).
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/backend; .venv\Scripts\python.exe -m pytest -q tests/test_api.py"</verify>
  <done>Existing API tests pass and the new WebSocket route is defined without syntax errors.</done>
</task>

## Success Criteria
- [ ] Backend accepts WebSocket connections at `/api/ws/stream`.
- [ ] Backend consumes SFeed from Kotak Neo and correctly broadcasts updates.
