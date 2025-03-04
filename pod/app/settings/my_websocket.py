import asyncio
from typing import Optional

from app.utility.my_logger import my_logger
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.ghost_connections: list[WebSocket] = []
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: Optional[str] = None):
        await websocket.accept()
        if user_id is not None:
            self.active_connections[user_id] = websocket
            my_logger.debug(f"User {user_id} connected")
        else:
            self.ghost_connections.append(websocket)
            my_logger.debug("👻 Anonymous (ghost) client connected")

    def disconnect(self, websocket: Optional[WebSocket] = None, user_id: Optional[str] = None):
        try:
            if user_id is not None:
                self.active_connections.pop(user_id, None)
                my_logger.debug(f"User {user_id} disconnected")
            elif websocket is not None:
                self.ghost_connections.remove(websocket)
                my_logger.debug("Anonymous (ghost) client disconnected")
        except Exception as e:
            my_logger.error(f"🚨 Exception while disconnecting: {e}")

    async def send_personal_message(self, user_id: str, data: dict):
        ws: Optional[WebSocket] = self.active_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(data=data)
            except Exception as e:
                my_logger.error(f"Exception while sending personal message: {e}")

    async def broadcast(self, data: dict, user_ids: Optional[list[str]] = None):
        my_logger.debug(f"broadcast self.active_connections: {self.active_connections}; data: {data}; user_ids: {user_ids}")
        if user_ids is not None:
            for user_id in user_ids:
                if user_id in self.active_connections:
                    asyncio.create_task(self.send_personal_message(user_id, data))
        else:
            for ghost in self.ghost_connections:
                await ghost.send_json(data)


admin_connection_manager = ConnectionManager()

metrics_connection_manager = ConnectionManager()

feed_connection_manager = ConnectionManager()
