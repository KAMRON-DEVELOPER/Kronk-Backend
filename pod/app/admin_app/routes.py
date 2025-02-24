# from app.users_app.models import UserModel
import asyncio
import random

from app.settings.my_minio import minio_ready
from app.settings.my_redis import CacheManager, my_redis, redis_om_ready
from app.utility.my_logger import my_logger
from fastapi import APIRouter, WebSocket  # WebSocketDisconnect
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

# Mock statistics data
statistics = {"registered_users": 100, "active_users": 50}


# Function to simulate real-time updates
async def update_statistics():
    global statistics
    while True:
        await asyncio.sleep(5)  # Update every 5 seconds
        statistics["total_users"] += random.randint(1, 5)
        statistics["active_users"] += random.randint(1, 3)


@admin_router.websocket(path="/ws/admin/statistics")
async def settings_metrics(websocket: WebSocket):
    await metrics_connection_manager.connect(websocket=websocket)
    print("🚧 Client connected")

    try:
        last_sent_stats = {}
        while True:
            new_stats = await cache_manager.get_statistics()

            my_logger.info(f"📊 last_sent_stats: {last_sent_stats}")
            my_logger.info(f"📊 new_stats: {new_stats}")
            my_logger.info(f"≈: {new_stats==last_sent_stats}")

            if new_stats != last_sent_stats:
                await metrics_connection_manager.broadcast(data=statistics)
                last_sent_stats = new_stats

            await asyncio.sleep(5)  # Send updates every 5 seconds
    except Exception as e:
        my_logger.critical(f"Exception in settings_metrics(admin): {e}")
    finally:
        metrics_connection_manager.disconnect(websocket)
