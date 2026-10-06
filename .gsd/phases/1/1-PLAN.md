---
phase: 1
plan: 1
wave: 1
---

# Plan 1.1: Historical Data Backend Support

## Objective
Implement backend functionality to fetch historical market data (candles) from the Kotak Neo API and expose it through a REST endpoint so the frontend charting components can consume it.

## Context
- .gsd/SPEC.md
- backend/app/brokers/base_broker.py
- backend/app/brokers/kotak_neo/kotak_broker.py
- backend/app/terminal/market.py
- backend/app/terminal/server.py

## Tasks

<task type="auto">
  <name>Extend Broker Interfaces for Historical Data</name>
  <files>
    - backend/app/brokers/base_broker.py
    - backend/app/brokers/kotak_neo/kotak_broker.py
    - backend/app/terminal/market.py
  </files>
  <action>
    - Update `BaseBroker` class in `base_broker.py` to include an abstract async method `get_historical_data(self, symbol: str, interval: str, from_date: str, to_date: str) -> dict`.
    - Implement `get_historical_data` in `KotakBroker` (`kotak_broker.py`) using `self.client.historical_data(neosymbol, interval, from_date, to_date)`. Ensure error handling is robust (catch exceptions and return generic empty series or error structure). Make it async and use `run_in_executor` if the Kotak client is blocking.
    - Update `MarketManager` in `market.py` to provide a passthrough async method `get_history(symbol, interval, from_date, to_date)` that calls `self.broker.get_historical_data`.
  </action>
  <verify>curl -s "http://127.0.0.1:8000/docs" > /dev/null && echo "Success"</verify>
  <done>KotakBroker successfully calls the `historical_data` method on the neo API client and returns the parsed JSON dict.</done>
</task>

<task type="auto">
  <name>Expose Historical Data REST Endpoint</name>
  <files>
    - backend/app/terminal/server.py
  </files>
  <action>
    - Add a new FastAPI `GET` route to `server.py`: `/api/market/history`.
    - It should accept query parameters: `symbol` (str), `interval` (str, default "D"), `from_date` (str, YYYY-MM-DD), `to_date` (str, YYYY-MM-DD).
    - It should call `await market.get_history(...)` and return the result as JSON.
    - Validate parameters and handle backend errors gracefully (return HTTP 500 or 400 instead of crashing).
  </action>
  <verify>curl -s "http://127.0.0.1:8000/api/market/history?symbol=nse_cm|2885&interval=D&from_date=2024-01-01&to_date=2024-01-10"</verify>
  <done>FastAPI serves the endpoint correctly, returning JSON data for valid requests.</done>
</task>

## Success Criteria
- [ ] Backend exposes `/api/market/history`.
- [ ] Returns structured candle data directly from Kotak Neo API.
