from typing import List
from fastapi import WebSocket
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.last_quotes: dict = {}
        self.user_ids: dict = {}

    async def connect(self, websocket: WebSocket, user_id: int = 1):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_ids[websocket]=user_id
        for quote in self.last_quotes.get(user_id,{}).values():
            try:
                await websocket.send_text(json.dumps({'type': 'QUOTE', 'data': quote}))
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        self.user_ids.pop(websocket,None)
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        user_id=message.get('user_id',1)
        message={k:v for k,v in message.items() if k!='user_id'}
        if message.get('type') == 'QUOTE' and 'data' in message:
            quote = message['data']
            if 'id' in quote:
                self.last_quotes.setdefault(user_id,{})[quote['id']] = quote

        # Convert message to JSON string once
        payload = json.dumps(message)
        
        # We need to handle disconnected clients gracefully 
        # in case they drop before we can send.
        dead_connections = []
        for connection in self.active_connections:
            if self.user_ids.get(connection,1)!=user_id:
                continue
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.append(connection)
                
        for dead in dead_connections:
            self.disconnect(dead)

# Global manager instance
manager = ConnectionManager()
