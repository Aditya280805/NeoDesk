from typing import List
from fastapi import WebSocket
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.last_quotes: dict = {}
        self.user_ids: dict = {}

    async def connect(self, websocket: WebSocket, user_id: int | None = None):
        if user_id is None or isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("Authenticated user_id is required for WebSocket connections.")
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_ids[websocket] = user_id
        for quote in self.last_quotes.get(user_id, {}).values():
            try:
                await websocket.send_text(json.dumps({'type': 'QUOTE', 'data': quote}))
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        self.user_ids.pop(websocket,None)
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        user_id = message.get('user_id')
        if user_id is None or isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            return
        # Remove user_id from message before sending
        message = {k: v for k, v in message.items() if k != 'user_id'}

        if message.get('type') == 'QUOTE' and 'data' in message:
            quote = message['data']
            if 'id' in quote:
                self.last_quotes.setdefault(user_id, {})[quote['id']] = quote

        payload = json.dumps(message)
        dead_connections = []
        for connection in list(self.active_connections):
            # Only send to connections with an explicit matching user_id (never None or default fallback)
            conn_user_id = self.user_ids.get(connection)
            if conn_user_id is None or conn_user_id != user_id:
                if conn_user_id is None:
                    dead_connections.append(connection)
                continue
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(dead)

# Global manager instance
manager = ConnectionManager()
