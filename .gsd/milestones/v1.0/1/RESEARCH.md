# Phase 1: Real-Time Infrastructure (WebSockets) - Research

## Objective
Determine the implementation pattern for live WebSocket streaming of quotes and order status using the official Kotak Neo Python SDK.

## Findings

1. **Market Data Streaming (SFeed)**
   - The Kotak Neo SDK uses an async/await WebSocket client called `SFeed`.
   - Access: `async with client.create_websocket() as ws:`
   - Subscribing to instruments: `await ws.subscribe_scrips([WsToken(exchange_segment, instrument_token)])`. Note that `WsToken` requires the exchange segment and the token, not the combined ID.
   - Message iteration: `async for message in ws:`
   - Message type: Returns `SFeedScrip` which contains `trading_symbol`, `instrument_token`, and `last_traded_price` (LTP).
   
2. **Order & Position Streaming**
   - The SDK provides a separate feed for order updates and positions.
   - Access: `async with client.create_order_feed() as feed:`
   - Message iteration: `async for message in feed:`
   - Message types: `OrderUpdate` (has `data.order_no`, `data.order_status`), `PositionUpdate` (has `data.symbol`).

3. **Integration with FastAPI**
   - We will need to wrap the SDK's async WebSocket clients in FastAPI background tasks or the existing `lifespan` context manager.
   - The consumed messages must be broadcasted to connected frontend clients via FastAPI WebSockets.

## Decisions
- Backend `websocket/` folder will be populated with a FastApi `WebSocketManager` to manage client connections and broadcast incoming data from Kotak Neo SDK.
- The `lifespan` hook in `server.py` will establish the `create_websocket()` and `create_order_feed()` connections to Kotak when the broker is authenticated.
