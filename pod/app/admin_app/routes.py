import asyncio

from taskiq import AsyncTaskiqTask

from app.settings.my_minio import minio_ready
from app.settings.my_redis import cache_manager, redis_om_ready
from app.settings.my_websocket import metrics_connection_manager
from app.utility.my_logger import my_logger
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse
from tortoise.exceptions import ConfigurationError
from app.users_app.models import UserModel
from bcrypt import gensalt, hashpw

from app.my_taskiq.my_taskiq import distribute_restore_tasks

admin_router = APIRouter()
admin_ws_router = APIRouter()


async def tortoise_ready() -> bool:
    try:
        await UserModel.all().count()
        return True
    except ConfigurationError as error:
        print(f"🌋 ConfigurationError in tortoise_ready: {error}")
        return False
    except Exception as error:
        print(f"🌋 Exception in tortoise_ready: {error}")
        return False


@admin_router.get(path="/ready", tags=["ready"])
async def ready():
    return {
        "tortoise": "🚀" if await tortoise_ready() else "🌋",
        "redis": "🚀" if await redis_om_ready() else "🌋",
        "minio": "🚀" if await minio_ready() else "🌋",
    }


@admin_router.get(path="/create_test_users")
async def create_test_users():
    if "some" != "not some":
        await UserModel.bulk_create(
            [
                UserModel(
                    username="alisher", email="alisheratajanov@gmail.com",
                    password=hashpw(password="alisher2009".encode(), salt=gensalt(rounds=8)).decode(),
                    avatar="users/images/alisher.jpg",
                ),
                UserModel(
                    username="kumush",
                    email="kumushatajanova@gmail.com",
                    password=hashpw(password="kumush2010".encode(), salt=gensalt(rounds=8)).decode(),
                    avatar="users/images/kumush.jpg",
                ),
                UserModel(
                    username="ravshan",
                    email="yangiboyevravshan@gmail.com",
                    password=hashpw(password="ravshan2004".encode(), salt=gensalt(rounds=8)).decode(),
                    avatar="users/images/ravshan.jpeg",
                ),
            ]
        )


@admin_router.get(path="/restore")
async def restore(target: str):
    try:
        await distribute_restore_tasks.kiq(target=target)

        return {"status": "sync started."}
    except Exception as exception:
        my_logger.critical(f"Exception in restore route. detail: {exception}")
        raise HTTPException(status_code=500, detail="🥶 🌋 🚨 OMG? Really terrible thing happened!")


@admin_ws_router.websocket(path="/ws/admin/statistics")
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
