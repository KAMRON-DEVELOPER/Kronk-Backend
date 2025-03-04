import asyncio
from typing import Optional

from app.admin_app.routes import metrics_connection_manager
from app.community_app.models import PostModel, FollowModel, PostCommentModel, PostReactionModel, PostViewModel, PostCommentReactionModel, PostCommentViewModel
from app.users_app.models import UserModel
from app.services.zepto_service import ZeptoMail
from app.settings.my_config import get_settings
from app.settings.my_redis import CacheManager, my_redis
from app.settings.my_websocket import feed_connection_manager
from app.utility.my_logger import my_logger
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend, RedisScheduleSource
from tortoise.expressions import F

cache_manager = CacheManager(redis=my_redis)

settings = get_settings()

broker = ListQueueBroker(
    url=settings.TASKIQ_WORKER_URL,
).with_result_backend(result_backend=RedisAsyncResultBackend(redis_url=settings.TASKIQ_SCHEDULER_URL, result_ex_time=600))

redis_schedule_source = RedisScheduleSource(url=settings.TASKIQ_REDIS_SCHEDULE_SOURCE_URL)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker=broker), redis_schedule_source],
)


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


@broker.task(task_name="send_new_post_notification_task")
async def send_new_post_notification_task(user_id: str) -> None:
    user_avatar_url: Optional[str] = await cache_manager.get_profile_avatar_url(user_id=user_id)
    my_logger.debug(f"send_new_post_notification_task: {user_avatar_url}")
    if user_avatar_url is None:
        user_avatar_url = "defaults/default-avatar.jpg"
    followers: set[str] = await cache_manager.get_followers(user_id=user_id)
    await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})


@broker.task(task_name="send_new_follower_notification_task")
async def send_new_follower_notification_task(user_id: str) -> None:
    user_avatar_url: Optional[str] = await cache_manager.get_profile_avatar_url(user_id=user_id)
    if user_avatar_url is not None:
        followers: set[str] = await cache_manager.get_followers(user_id=user_id)
        await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})


@broker.task()
async def distribute_restore_tasks(target: str):
    batch_size = 1000
    limit = 1000

    models = [
        (UserModel, "user:*"),
        (PostModel, "post:*"),
        (PostCommentModel, "post_comment:*"),
        (PostReactionModel, "post_reaction:*"),
        (PostViewModel, "post_view:*"),
        (PostCommentReactionModel, "post_comment_reaction:*"),
        (PostCommentViewModel, "post_comment_view:*"),
    ]

    for model, pattern in models:
        if target == "redis":
            await distribute_tasks_for_model(model, target, batch_size)
        elif target == "db":
            await distribute_tasks_for_model(model, target, batch_size)


async def distribute_tasks_for_model(model, target: str, batch_size: int):
    total_count = await model.all().count()
    rounds = total_count // batch_size
    remaining = total_count % batch_size

    for i in range(0, rounds):
        if target == "redis":
            await sync_batch_from_db_to_redis.kiq(offset=i * batch_size, limit=batch_size)
        elif target == "db":
            await sync_batch_from_redis_to_db.kiq(offset=i * batch_size, limit=batch_size)

    if remaining > 0:
        if target == "redis":
            await sync_batch_from_db_to_redis.kiq(offset=rounds * batch_size, limit=remaining)
        elif target == "db":
            await sync_batch_from_redis_to_db.kiq(offset=rounds * batch_size, limit=remaining)


@broker.task()
async def sync_batch_from_db_to_redis(offset: int = 0, limit: int = 100):
    # Fetch users in the chunk
    users = await UserModel.filter().offset(offset).limit(limit).all()
    if users:
        await cache_manager.create_users(
            mappings=[
                {
                    "id": user.id,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                    "username": user.username,
                    "email": user.email,
                    "password": user.password,
                    "bio": user.bio
                } for user in users
            ],
        )

    # Fetch posts in the chunk
    posts = await PostModel.filter().offset(offset).limit(limit).all()
    if posts:
        await cache_manager.create_posts(
            mappings=[
                {
                    "id": post.id,
                    "created_at": post.created_at,
                    "updated_at": post.updated_at,
                    "author": post.author,
                    "body": post.body,
                    "post_views": post.post_views,
                    "post_reactions": post.post_reactions
                } for post in posts
            ],
        )


@broker.task()
async def sync_batch_from_redis_to_db(offset: int = 0, limit: int = 100, batch_size: int = 100):
    pass
