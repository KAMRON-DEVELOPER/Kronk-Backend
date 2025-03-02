import asyncio
from typing import Optional

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend
from tortoise.expressions import F

from app.admin_app.routes import metrics_connection_manager
from app.community_app.models import PostModel
from app.community_app.routes import feed_connection_manager
from app.services.zepto_service import ZeptoMail
from app.settings.my_config import get_settings
from app.settings.my_redis import CacheManager, my_redis
from app.utility.my_logger import my_logger

cache_manager = CacheManager(redis=my_redis)

settings = get_settings()

broker = ListQueueBroker(
    url=settings.TASKIQ_WORKER_URL,
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url=settings.TASKIQ_SCHEDULER_URL, result_ex_time=600))

scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker=broker)])


@broker.task(task_name="send_email_task")
async def send_email_task(to_email: str, username: str, code: str = "0000", for_reset_password: bool = False, for_thanks_signing_up: bool = False):
    zepto = ZeptoMail()
    await zepto.send_email(to_email, username, code, for_reset_password, for_thanks_signing_up)


@broker.task(task_name="broadcast_stats_to_settings_task")
async def broadcast_stats_to_settings_task() -> None:
    last_sent_stats = {}
    try:
        new_stats = await cache_manager.get_statistics()

        my_logger.info(f"📊 last_sent_stats: {last_sent_stats}")
        my_logger.info(f"📊 new_stats: {new_stats}")
        my_logger.info(f"≈: {new_stats == last_sent_stats}")

        if new_stats != last_sent_stats:
            await metrics_connection_manager.broadcast(data=new_stats)
            last_sent_stats = new_stats  # noqa
    except Exception as e:
        my_logger.critical(f"Exception in broadcast_stats_to_settings_task: {e}")


@broker.task(schedule=[{"cron": "*/60 * * * *"}], task_name="sync_post_stats_task")
async def sync_post_statistics_to_db_task() -> None:
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


@broker.task()
async def send_new_post_notification_task(user_id: str) -> None:
    user_avatar_url: Optional[str] = await cache_manager.get_user_avatar_url(user_id=user_id)
    if user_avatar_url is not None:
        followers: set[str] = await cache_manager.get_followers(user_id=user_id)
        await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})


@broker.task()
async def send_new_follower_notification_task(user_id: str) -> None:
    user_avatar_url: Optional[str] = await cache_manager.get_user_avatar_url(user_id=user_id)
    if user_avatar_url is not None:
        followers: set[str] = await cache_manager.get_followers(user_id=user_id)
        await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})
