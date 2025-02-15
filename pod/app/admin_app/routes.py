# from app.users_app.models import UserModel
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from tortoise.exceptions import ConfigurationError

from app.settings.my_minio import minio_ready
from app.settings.my_redis import CacheManager, my_redis, redis_om_ready

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


async def send_personal_message(message: str, websocket: WebSocket):
    await websocket.send_text(data=message)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(data=message)


admin_connection_manager = ConnectionManager()


@admin_router.websocket(path="")
async def websocket_endpoint(websocket: WebSocket):
    await admin_connection_manager.connect(websocket=websocket)
    print("🚧 Client connected")
    try:
        while True:
            data: str = await websocket.receive_text()
            await admin_connection_manager.broadcast(message=f"📡 {data}")
    except WebSocketDisconnect:
        admin_connection_manager.disconnect(websocket=websocket)
        print("🚧 Client disconnected")


@admin_router.websocket(path="/stats")
async def websocket_endpoint(websocket: WebSocket):
    await admin_connection_manager.connect(websocket=websocket)
    print("🚧 Client connected")

    # Send the current user count on connection
    user_count = await cache_manager.get_user_count()
    await websocket.send_text(f"User Count: {user_count}")

    try:
        while True:
            data: str = await websocket.receive_text()
            await admin_connection_manager.broadcast(f"📡 {data}")
    except WebSocketDisconnect:
        admin_connection_manager.disconnect(websocket)
        print("🚧 Client disconnected")
