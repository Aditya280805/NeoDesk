---
phase: 2
plan: 1
wave: 1
---

# Plan 2.1: Live Order Execution Engine

## Objective
Implement real-money order routing to Kotak Neo via the `neo_api_client`. Create a secure endpoint structure that allows placing, modifying, and cancelling live orders, while strictly isolating them from paper trades.

## Context
- .gsd/SPEC.md
- `neo-trading-terminal/backend/app/terminal/server.py`
- `neo-trading-terminal/backend/app/terminal/paper.py`

## Tasks

<task type="auto">
  <name>Live Trading Module Implementation</name>
  <files>
    neo-trading-terminal/backend/app/terminal/live.py
  </files>
  <action>
    - Create `live.py` echoing the `paper.py` endpoints but routing to the live Kotak API (`place_order`, `modify_order`, `cancel_order`).
    - Expose endpoints: `GET /live`, `POST /live/orders`, `PUT /live/orders/{id}`, `DELETE /live/orders/{id}`.
    - Implement error handling utilizing `neo_api_client.exceptions` to catch AuthenticationError, ValidationError, OrderError, etc. and return 400/500 HTTP exceptions.
    - Include the `validate_session` dependency just like in `paper.py` to ensure the Kotak client is logged in before placing live orders.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/backend; & pytest tests/ -k 'test_live'"</verify>
  <done>The `live.py` module exposes order management endpoints integrated with the real API and handles errors securely.</done>
</task>

<task type="auto">
  <name>Register Live Routes</name>
  <files>
    neo-trading-terminal/backend/app/terminal/server.py
  </files>
  <action>
    - Import the `live` router from `live.py`.
    - Include the router in the FastAPI `app` with the `/api` prefix, similar to `paper_router`.
  </action>
  <verify>powershell -Command "cd neo-trading-terminal/backend; & python -c \"import app.terminal.server\""</verify>
  <done>Live trading endpoints are registered under `/api/live`.</done>
</task>

## Success Criteria
- [ ] A dedicated `/api/live` endpoint exists and routes to Kotak Neo APIs.
- [ ] Appropriate exception handling prevents unauthenticated/malformed requests from crashing the server.
