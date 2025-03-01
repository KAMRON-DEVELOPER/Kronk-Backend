import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from app.community_app.models import PostModel, ReactionEnum
from app.settings.my_config import get_settings
from app.users_app.models import UserModel
from app.utility.my_logger import my_logger
from redis.asyncio import Redis

my_redis = Redis.from_url(url=f"{get_settings().REDIS_URL}", decode_responses=True, auto_close_connection_pool=True)


async def redis_om_ready() -> bool:
    try:
        await my_redis.ping()
        return True
    except Exception as e:
        print(f"🌋 Failed in redis_om_ready: {e}")
        return False


class CacheManager:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.global_timeline_key = "global_timeline"
        self.home_timeline_prefix = "home_timeline:"
        self.user_timeline_prefix = "user_timeline:"
        self.post_stats_prefix = "post_stats:"
        self.post_timestamp_key = "post_timestamp"
        self.post_meta_prefix = "post_meta:"
        self.followers_prefix = "followers:"
        self.followings_prefix = "followings:"
        self.user_profile_prefix = "user_profile:"
        self.user_event_prefix = "user_event:"
        self.register_prefix = "register:"
        self.reset_password_prefix = "reset_password:"

    ## ---------------------------------------- TIMELINE MANAGEMENT ----------------------------------------
    async def _add_post_to_gt(self, post_id: str, amount: int = 180) -> None:
        """Add post ID to global timeline and keep only the latest amount of posts."""
        await self.redis.hset(name=f"{self.post_timestamp_key}", key=f"{post_id}", value=f"{int(time.time())}")
        if await self.redis.zcard(name=f"{self.global_timeline_key}") < amount:
            await self.redis.zadd(name=self.global_timeline_key, mapping={post_id: 0})

    async def get_global_timeline(self, start: int = 0, end: int = 19) -> list[dict]:
        """Get global timeline with post metadata and statistics."""
        gt_post_ids: list[str] = await self.redis.zrevrange(name=self.global_timeline_key, start=start, end=end)
        my_logger.debug(f"gt_post_ids: {gt_post_ids}")
        if not gt_post_ids:
            return []

        gt_posts = await self._get_posts(post_ids=gt_post_ids)
        my_logger.debug(f"gt_posts: {gt_posts}")
        return gt_posts

    async def add_post_to_ht(self, user_id: str, post_id: str, start: int = 0, end: int = 59) -> None:
        """Add post to home timeline and trim in specified range"""
        await self.redis.lpush(f"{self.home_timeline_prefix}{user_id}", post_id)
        await self.redis.ltrim(name=f"{self.home_timeline_prefix}{user_id}", start=start, end=end)

    async def get_home_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get home timeline with post metadata, merging user's feed with global timeline."""
        ht_post_ids: list[str] = await self.redis.lrange(name=f"{self.home_timeline_prefix}{user_id}", start=start, end=end)

        if not ht_post_ids:
            return await self.get_global_timeline(start, end)

        return await self._get_posts(post_ids=ht_post_ids)

    async def add_post_to_ut(self, user_id: str, post_id: str, start: int = 0, end: int = 4000):
        """Push post ID to user timeline in Redis List."""
        await self.redis.lpush(f"{self.user_timeline_prefix}{user_id}", post_id)
        await self.redis.ltrim(name=f"{self.user_timeline_prefix}{user_id}", start=start, end=end)

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get user timeline posts with stats."""
        ut_post_ids = await self.redis.lrange(name=f"{self.user_timeline_prefix}{user_id}", start=start, end=end)

        if not ut_post_ids:
            return []

        my_logger.debug(f"user_timeline_post_ids: {ut_post_ids}")
        # Fetch post metadata and stats
        return await self._get_posts(post_ids=ut_post_ids)

    async def get_single_post(self, post_id: str) -> dict:
        """Get single post with given specific post id."""
        posts = await self._get_posts(post_ids=[post_id])
        return posts[0] if posts else {}

    async def update_post_stats(self, post_id: str, key: str, value: str):
        """Update post statistics and recalculate score dynamically."""
        await self.redis.hset(name=f"{self.post_stats_prefix}{post_id}", key=key, value=value)

        # Fetch all stats
        stats_dict_bytes = await self.redis.hgetall(f"{self.post_stats_prefix}{post_id}")
        stats = {k.decode(): int(v.decode()) for k, v in stats_dict_bytes.items()} if stats_dict_bytes else {}

        # Retrieve timestamp
        created_at_bytes = await self.redis.hget(name=f"{self.post_timestamp_key}", key=f"{post_id}")
        created_at = int(created_at_bytes) if created_at_bytes else int(time.time())

        # Calculate new ranking score
        score = calculate_score(stats=stats, created_at=created_at)

        await self.redis.zadd(name=self.global_timeline_key, mapping={post_id: score})
        await self.redis.zremrangebyrank(name=self.global_timeline_key, min=0, max=180)

    async def _get_posts_stats(self, post_ids: list[str]) -> list[tuple[int, int, int, int, int, int]]:
        """Fetch stats for multiple posts using a Redis pipeline."""

        async with self.redis.pipeline() as pipe:
            [pipe.hgetall(f"{self.post_stats_prefix}{post_id}") for post_id in post_ids]
            stats_dict = await pipe.execute()

        # Convert stats dictionary and use list comprehension for efficiency
        return [scores_getter(stats={k: int(v) for k, v in stats_dict.items()} if stats_dict else {}) for stats_dict in stats_dict]

    async def _get_posts(self, post_ids: list[str]) -> list[dict]:
        """Fetch post metadata and bind stats to posts."""
        async with self.redis.pipeline() as pipe:
            [pipe.hgetall(f"{self.post_meta_prefix}{post_id}") for post_id in post_ids]
            post_dict_list: list[dict] = await pipe.execute()

        my_logger.debug(f"post_dict_list: {post_dict_list}")
        # Ensure the list comprehension structure is used efficiently
        posts = [post_dict for post_dict in post_dict_list if post_dict]
        my_logger.debug(f"posts: {posts}")

        stats_list = await self._get_posts_stats(post_ids=post_ids)
        my_logger.debug(f"stats_list: {stats_list}")

        # Bind stats to posts
        for post, stats in zip(posts, stats_list):
            post.update({"comments": stats[0], "reposts": stats[1], "quotes": stats[2], "likes": stats[3], "dislikes": stats[4], "views": stats[5]})

        return posts

    ## ---------------------------------------- POSTS MANAGEMENT ----------------------------------------

    async def create_post(self, user_id: str, new_post: PostModel):
        try:
            post_mapping = {
                "id": new_post.id,
                "created_at": new_post.created_at,
                "updated_at": new_post.updated_at,
                "author": user_id,
                "body": new_post.body,
                "scheduled_time": new_post.scheduled_time,
                "images": new_post.images,
                "video": new_post.video,
            }

            await self.redis.hset(name=f"{self.post_meta_prefix}{new_post.id}", mapping={k: v for k, v in post_mapping.items() if v})

            # Add to global timeline
            await self._add_post_to_gt(post_id=str(new_post.id.hex))

            followers = await self.get_followers(user_id=user_id)
            for follower_id in followers:
                await self.add_post_to_ht(user_id=follower_id, post_id=str(new_post.id.hex))
        except Exception as e:
            my_logger.error(f"Exceptions while creating post: {e}")
            raise ValueError(f"Exceptions while creating post: {e}")

    async def delete_post(self, post_id: str, user_id: str):
        """Completely remove post related things from all places."""
        pipe = self.redis.pipeline()

        # Remove post from all users' home timelines
        await pipe.zrem(self.global_timeline_key, post_id)
        followers: set[str] = await self.get_followers(user_id=user_id)
        for follower_id in followers:
            await pipe.lrem(name=f"{self.home_timeline_prefix}{follower_id}", count=0, value=post_id)

        # Remove post from author's timeline
        await pipe.lrem(name=f"{self.user_timeline_prefix}{user_id}", count=0, value=post_id)

        # Delete post metadata and stats
        await pipe.delete(f"{self.post_meta_prefix}{post_id}", f"{self.post_stats_prefix}{post_id}", f"{self.post_timestamp_key}{post_id}")

        await pipe.execute()

    ## ---------------------------------------- FOLLOWERS & FOLLOWINGS MANAGEMENT ----------------------------------------

    async def add_follower(self, user_id: str, follower_id: str):
        """Add a follower or multiple followers to the user."""
        async with self.redis.pipeline() as pipe:
            pipe.sadd(f"{self.followers_prefix}{follower_id}", user_id)
            pipe.sadd(f"{self.followings_prefix}{user_id}", follower_id)
            await pipe.execute()

    async def remove_follower(self, user_id: str, follower_id: str):
        """Remove a follower relationship."""
        async with self.redis.pipeline() as pipe:
            await self.redis.srem(f"{self.followings_prefix}{user_id}", follower_id)
            await self.redis.srem(f"{self.followers_prefix}{follower_id}", user_id)
            await pipe.execute()

    async def get_followers(self, user_id: str) -> set[str]:
        """Get all followers of a user."""
        return await self.redis.smembers(f"{self.followers_prefix}{user_id}")

    async def get_following(self, user_id: str) -> set[str]:
        """Get all users that a user is following."""
        return await self.redis.smembers(f"{self.followings_prefix}{user_id}")

    async def is_following(self, user_id: str, follower_id: str) -> bool:
        """Check if a user is following another user."""
        return await self.redis.sismember(name=f"{self.followings_prefix}{user_id}", value=follower_id)

    ## ---------------------------------------- USER PROFILE MANAGEMENT ----------------------------------------

    async def update_user_profile(self, data: dict):
        pass

    async def create_user_profile(self, new_user: UserModel):
        try:
            """Create user profile storing only non-empty fields"""
            fields = ["id", "created_at", "updated_at", "first_name", "last_name", "username", "email", "password", "avatar", "banner", "banner_color", "birthdate", "bio", "country", "state_or_province"]
            user_mapping = {}
            for field in fields:
                value = getattr(new_user, field, None)
                if value is not None:
                    if isinstance(value, UUID):
                        user_mapping[field] = value.hex
                    elif isinstance(value, datetime):
                        user_mapping[field] = value.isoformat()
                    else:
                        user_mapping[field] = value

            # await self.redis.hset(name=f"{self.user_profile_prefix}{new_user.id.hex}", mapping=user_mapping)

            async with self.redis.pipeline() as pipe:
                my_logger.info(f"🚧 mapping: {user_mapping}")
                await pipe.hset(name=f"{self.user_profile_prefix}{new_user.id.hex}", mapping=user_mapping).sadd("profiles", new_user.id.hex).hset(name="usernames", mapping={new_user.username: new_user.id.hex}).hset(name="emails", mapping={new_user.email: "1"}).execute()
        except Exception as e:
            raise ValueError(f"🥶 Exception in create_user_profile: {e}")

    async def get_user_profile(self, user_id: str) -> dict:
        """Retrieve user profile details."""
        profile_dict: dict = await self.redis.hgetall(f"{self.user_profile_prefix}{user_id}")
        return {k: v for k, v in profile_dict.items()} if profile_dict else {}

    async def get_user_profile_by_username(self, username: str) -> dict:
        user_id: Optional[str] = await self.redis.hget(name="usernames", key=username)
        if user_id is None:
            return {}
        return await self.get_user_profile(user_id=user_id)

    async def get_user_avatar_url(self, user_id: str) -> Optional[str]:
        return await self.redis.hget(f"{self.user_profile_prefix}{user_id}", key="avatar")

    async def delete_user_profile(self, user_id: str, username: str, email: str):
        """Delete a user profile and associated data."""

        async with my_redis.pipeline() as pipe:

            # Delete user profile and all related keys
            pipe.delete(f"{self.home_timeline_prefix}{user_id}", f"{self.user_timeline_prefix}{user_id}", f"{self.user_profile_prefix}{user_id}", f"{self.followers_prefix}{user_id}", f"{self.followings_prefix}{user_id}")
            pipe.srem("profiles", user_id)
            pipe.hdel("usernames", username)
            pipe.hdel("emails", email)

            await pipe.execute()

        post_ids: list[str] = await self.redis.lrange(name=f"{self.user_timeline_prefix}{user_id}", start=0, end=-1)
        my_logger.info(f"post_ids: {post_ids}")
        for post_id in post_ids:
            await self.delete_post(post_id, user_id)

        # Remove follow relationships
        followers: set[str] = await self.get_followers(user_id)
        following: set[str] = await self.get_following(user_id)

        my_logger.info(f"followers: {followers}, following: {following}")

        for follower_id in followers:
            pipe.srem(f"{self.followings_prefix}{follower_id}", user_id)

        for followed_id in following:
            pipe.srem(f"{self.followers_prefix}{followed_id}", user_id)

    ## ---------------------------------------- TRACK USER ACTIONS ----------------------------------------

    async def mark_post_as_viewed(self, user_id: str, post_id: str):
        await self.redis.hset(name=f"{self.user_event_prefix}{user_id}", key=post_id, value="")

    async def track_user_reaction_to_post(self, user_id: str, post_id: str, reaction: ReactionEnum):
        pass

    async def mark_comment_as_viewed(self, user_id: str, comment_id: str):
        await self.redis.hset(name=f"{self.user_event_prefix}{user_id}", key=comment_id, value="")

    async def track_user_reaction_to_comment(self, user_id: str, comment_id: str, reaction: ReactionEnum):
        pass

    ## ---------------------------------------- KRONK STATISTICS ----------------------------------------
    async def get_user_count(self) -> int:
        users_count = await self.redis.hget("registered_users", key="users_count")
        if not users_count:
            return 0
        return int(users_count)

    async def exists(self, name: str):
        return await self.redis.exists(name)

    async def get_statistics(self) -> dict:
        statistics = await self.redis.hgetall("statistics")
        if not statistics:
            return {"registered_users": 0, "daily_active_users": 0}
        return statistics

    async def get_usernames(self, username_query: Optional[str] = None):
        if username_query is not None:
            keys = await self.redis.hkeys(name="usernames")
            pattern = re.compile(username_query, re.IGNORECASE)
            return [key for key in keys if pattern.search(key)]
        return await self.redis.hkeys(name="usernames")

    ## ---------------------------------------- REGISTRATION & RESET PASSWORD CREDENTIALS ----------------------------------------
    async def set_registration_credentials(self, username: str, email: str, password: str, code: str, expiry: int = 600) -> tuple[str, str]:
        """Store registration credentials and return token and expiration time."""
        verify_token = uuid4().hex
        await self.redis.hset(
            name=f"{self.register_prefix}{verify_token}",
            mapping={"username": username, "email": email, "password": password, "code": code},
        )
        await self.redis.expire(name=f"{self.register_prefix}{verify_token}", time=expiry)
        return verify_token, (datetime.now() + timedelta(seconds=expiry)).isoformat()

    async def get_registration_credentials(self, verify_token: str) -> dict:
        """Retrieve registration credentials."""
        return await self.redis.hgetall(name=f"{self.register_prefix}{verify_token}")

    async def remove_registration_credentials(self, verify_token: str):
        """Delete registration credentials."""
        await self.redis.delete(f"{self.register_prefix}{verify_token}")

    async def set_reset_password_credentials(self, email: str, code: str, expiry: int = 600) -> tuple[str, str]:
        """Store password reset credentials and return token and expiration time."""
        reset_password_token = uuid4().hex
        await self.redis.hset(
            name=f"{self.reset_password_prefix}{reset_password_token}",
            mapping={"email": email, "code": code},
        )
        return reset_password_token, (datetime.now() + timedelta(seconds=expiry)).isoformat()

    async def get_reset_password_credentials(self, reset_password_token: str) -> dict:
        """Retrieve password reset credentials."""
        return await self.redis.hgetall(f"{self.reset_password_prefix}{reset_password_token}")

    async def remove_reset_password_credentials(self, reset_password_token: str):
        """Delete password reset credentials."""
        await self.redis.delete(f"{self.reset_password_prefix}{reset_password_token}")

    async def is_someone_registering_with_this_username_and_email(self, username: str, email: str) -> tuple[bool, bool]:
        """Check if a username and email is currently in the registration process."""
        is_username_exist = False
        is_email_exist = False

        async for name in self.redis.scan_iter(match=f"{self.register_prefix}*"):
            registered_username = await self.redis.hget(name=name, key="username")
            if registered_username and registered_username == username:
                is_username_exist = True

        async for name in self.redis.scan_iter(match=f"{self.register_prefix}*"):
            registered_email = await self.redis.hget(name=name, key="email")
            if registered_email and registered_email == email:
                is_email_exist = True

        return is_username_exist, is_email_exist

    async def is_user_already_exist_with_this_username_and_email(self, username: str, email: str) -> tuple[bool, bool]:
        """Check if a username and email already exist in database."""
        async with self.redis.pipeline() as pipe:
            await pipe.hexists(name="usernames", key=username)
            await pipe.hexists(name="emails", key=email)
            is_username_already_exist, is_email_already_exist = await pipe.execute()

        return is_username_already_exist, is_email_already_exist


def scores_getter(stats: dict) -> tuple[int, int, int, int, int, int]:
    return stats.get("comments", 0), stats.get("reposts", 0), stats.get("quotes", 0), stats.get("likes", 0), stats.get("dislikes", 0), stats.get("views", 0)


def calculate_score(stats: dict, created_at: int, half_life: float = 36, boost_factor: int = 12) -> float:
    """Calculate post ranking score using weighted metrics and time decay."""
    comments, reposts, quotes, likes, _, views = scores_getter(stats=stats)
    age_hours = (time.time() - created_at) / 3600

    # Weighted Engagement Score (log-scaled)
    engagement_score = math.log(1 + comments * 5 + reposts * 3 + quotes * 4 + likes * 2 + views * 0.5)

    # Exponential Decay (half-life controls decay speed)
    time_decay = math.exp(-age_hours / half_life)

    # Freshness Boost (soft decay instead of sharp drop)
    freshness_boost = 10 * math.exp(-age_hours / boost_factor)

    # Final Score
    return (engagement_score * time_decay) + freshness_boost
