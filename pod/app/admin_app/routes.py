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
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, data: dict):
        for connection in self.active_connections:
            await connection.send_json(data=data)


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
            data = await websocket.receive_text()
            my_logger.info(f"📨 received_text in settings_metrics data: {data}")
    except WebSocketDisconnect:
        my_logger.info("👋 websocket connection is closing...")
        metrics_connection_manager.disconnect(websocket)
