import asyncio
from typing import Optional

from app.settings.my_minio import minio_ready
from app.settings.my_redis import CacheManager, my_redis, redis_om_ready
from app.utility.my_logger import my_logger
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from tortoise.exceptions import ConfigurationError

admin_router = APIRouter()

cache_manager = CacheManager(redis=my_redis)


@admin_router.get(path="/ready", tags=["ready"])
async def ready():
    return {
        "tortoise": "🚀" if await tortoise_ready() else "🌋",
        "redis": "🚀" if await redis_om_ready() else "🌋",
        "minio": "🚀" if await minio_ready() else "🌋",
    }


async def tortoise_ready() -> bool:
    try:
        # await UserModel.all().count()
        return True
    except ConfigurationError as error:
        print(f"🌋 ConfigurationError in tortoise_ready: {error}")
        return False
    except Exception as error:
        print(f"🌋 Exception in tortoise_ready: {error}")
        return False


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
        my_logger.debug(f"self.active_connections: {self.active_connections}; data: {data}; user_ids: {user_ids}")
        if user_ids is not None:
            for user_id in user_ids:
                if user_id in self.active_connections:
                    asyncio.create_task(self.send_personal_message(user_id, data))
        else:
            for ghost in self.ghost_connections:
                await ghost.send_json(data)


admin_connection_manager = ConnectionManager()

metrics_connection_manager = ConnectionManager()


@admin_router.websocket(path="/ws/admin/statistics")
async def settings_metrics(websocket: WebSocket):
    await metrics_connection_manager.connect(websocket=websocket)
    print("🚧 Client connected")

    statistics = await cache_manager.get_statistics()
    await metrics_connection_manager.broadcast(data=statistics)

    try:
        while True:
            await asyncio.sleep(1)
            data = await websocket.receive_json()
            my_logger.info(f"📨 received_text in settings_metrics data: {data}")
    except WebSocketDisconnect:
        my_logger.info("👋 websocket connection is closing...")
        metrics_connection_manager.disconnect(websocket=websocket)
