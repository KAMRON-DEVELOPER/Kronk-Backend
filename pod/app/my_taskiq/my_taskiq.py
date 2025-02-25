import asyncio

import aiohttp
from app.admin_app.routes import metrics_connection_manager
from app.community_app.models import PostModel
from app.settings.my_config import get_settings
from app.settings.my_redis import CacheManager, my_redis
from app.utility.my_logger import my_logger
from fastapi import APIRouter
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from tortoise.expressions import F

admin_router = APIRouter()

cache_manager = CacheManager(redis=my_redis)

broker = ListQueueBroker(
    url="redis://default:kamronbek2003@localhost:6379/1",
    queue_name="fastapi_taskiq_queue",
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url="redis://default:kamronbek2003@localhost:6379/2", result_ex_time=600))

scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker=broker)])


@broker.task(task_name="send_email_task")
async def send_email_task(to_email: str, username: str, code: str = "0000", for_reset_password: bool = False, for_thanks_signing_up: bool = False):
    zepto = ZeptoMail()
    await zepto.send_email(to_email, username, code, for_reset_password, for_thanks_signing_up)


class ZeptoMail:
    API_URL = "https://api.zeptomail.com/v1.1/email/template"
    HEADERS = {"accept": "application/json", "content-type": "application/json", "authorization": f"Zoho-enczapikey {get_settings().EMAIL_SERVICE_API_KEY}"}

    @staticmethod
    async def send_email(to_email: str, username: str, code: str = "0000", for_reset_password: bool = False, for_thanks_signing_up: bool = False):
        payload = {
            "template_alias": "kronk-verification-key-alias",
            "from": {"address": "verify@kronk.uz", "name": "verify"},
            "to": [{"email_address": {"name": username, "address": to_email}}],
            "merge_info": {"code": code, "username": username},
        }
        if for_reset_password:
            payload.update({"template_alias": "kronk-password-reset-key-alias", "from": {"address": "reset@kronk.uz", "name": "reset"}})
        if for_thanks_signing_up:
            payload.update({"template_alias": "kronk-thanks-for-signing-up-key-alias", "from": {"address": "thanks@kronk.uz", "name": "thanks"}})

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url=ZeptoMail.API_URL, json=payload, headers=ZeptoMail.HEADERS) as response:
                    return {"status": response.status, "message": (await response.json())["message"]}
            except Exception as e:
                print(f"🌋 Exception in ZeptoMail send_email: {e}")
                return {"status": "🌋"}


last_sent_stats = {}


@broker.task(task_name="broadcast_stats_to_settings_task")
async def broadcast_stats_to_settings_task() -> None:
    global last_sent_stats
    try:
        new_stats = await cache_manager.get_statistics()

        my_logger.info(f"📊 last_sent_stats: {last_sent_stats}")
        my_logger.info(f"📊 new_stats: {new_stats}")
        my_logger.info(f"≈: {new_stats==last_sent_stats}")

        if new_stats != last_sent_stats:
            await metrics_connection_manager.broadcast(data=new_stats)
            last_sent_stats = new_stats
    except Exception as e:
        my_logger.critical(f"Exception in broadcast_stats_to_settings_task: {e}")


@broker.task(schedule=[{"cron": "*/60 * * * *"}], task_name="sync_post_stats_task")
async def sync_post_stats_task() -> None:
    print("🗓️ process_sync_events is started...")
    await asyncio.sleep(delay=60)
    print("🗓️ process_sync_events is finished...")

    try:
        ready = "not"
        if ready == "ready":
            async with my_redis.pipeline() as _:
                keys = await my_redis.keys("post:*:stats")  # Get all tracked posts
                updates = {}

                for key in keys:
                    post_id = key.split(":")[1]
                    stats = await my_redis.hgetall(key)

                    updates[post_id] = {
                        "views": int(stats.get("views", 0)),
                        "likes": int(stats.get("likes", 0)),
                        "dislikes": int(stats.get("dislikes", 0)),
                    }

                # Bulk update database
                for post_id, data in updates.items():
                    await PostModel.filter(id=post_id).update(
                        views_count=F("views_count") + data["views"],
                        likes_count=F("likes_count") + data["likes"],
                        dislikes_count=F("dislikes_count") + data["dislikes"],
                    )

                # Clear Redis counters after syncing
                await my_redis.delete(*keys)
    except Exception as e:
        print(f"Error updating view count: {e}")
