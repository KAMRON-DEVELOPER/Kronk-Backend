import json
import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.community_app.models import ReactionEnum
from app.settings.my_config import get_settings
from app.users_app.models import UserModel
from app.utility.my_logger import my_logger

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
        self.post_meta_prefix = "post_meta:"
        self.post_stats_prefix = "post_stats:"
        self.followers_prefix = "followers:"
        self.followings_prefix = "followings:"
        self.user_profile_prefix = "user_profile:"
        self.user_event_prefix = "user_event:"
        self.register_prefix = "register:"
        self.forgot_password_prefix = "forgot_password:"

    # ******************************************************************* TIMELINE MANAGEMENT *******************************************************************

    async def get_global_timeline(self, start: int = 0, end: int = 19) -> list[dict]:
        """Get global timeline with post metadata and statistics."""
        gt_post_ids: list[str] = await self.redis.zrevrange(name=self.global_timeline_key, start=start, end=end)
        return await self._get_posts(post_ids=gt_post_ids)

    async def get_home_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get home timeline with post metadata, merging user's feed with global timeline."""
        ht_post_ids: list[str] = await self.redis.lrange(name=f"{self.home_timeline_prefix}{user_id}", start=start, end=end)
        if not ht_post_ids:
            return await self.get_global_timeline(start, end)
        return await self._get_posts(post_ids=ht_post_ids)

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get user timeline posts with stats."""
        ut_post_ids = await self.redis.lrange(name=f"{self.user_timeline_prefix}{user_id}", start=start, end=end)
        return await self._get_posts(post_ids=ut_post_ids)

    async def get_single_post(self, post_id: str) -> dict:
        """Get single post with given specific post id."""
        posts = await self._get_posts(post_ids=[post_id])
        return posts[0] if posts else {}

    async def _get_posts(self, post_ids: list[str]) -> list[dict]:
        """Fetch post metadata and bind stats to posts."""
        if not post_ids:
            return []

        async with self.redis.pipeline() as pipe:
            [pipe.hgetall(f"{self.post_meta_prefix}{post_id}") for post_id in post_ids]
            post_dict_list: list[dict] = await pipe.execute()

            my_logger.debug(f"post_dict_list: {post_dict_list}")

            # Deserialize the 'images' field back into a list
            for post_dict in post_dict_list:
                if "images" in post_dict:
                    try:
                        post_dict["images"] = json.loads(post_dict["images"])
                    except json.JSONDecodeError:
                        my_logger.error(f"Failed to deserialize images for post: {post_dict}")
                        post_dict["images"] = []

        posts = [post_dict for post_dict in post_dict_list if post_dict]
        my_logger.debug(f"posts: {posts}")

        stats_list = await self._get_posts_stats(post_ids=post_ids)
        my_logger.debug(f"stats_list: {stats_list}")

        # Bind stats to posts
        for post, stats in zip(posts, stats_list):
            post.update({"comments": stats[0], "likes": stats[1], "dislikes": stats[2], "views": stats[3]})

        return posts

    async def _get_posts_stats(self, post_ids: list[str]) -> list[tuple[int, int, int, int]]:
        """Fetch stats for multiple posts using a Redis pipeline."""
        async with self.redis.pipeline() as pipe:
            [pipe.hgetall(f"{self.post_stats_prefix}{post_id}") for post_id in post_ids]
            stats_dict_list: list[dict] = await pipe.execute()

        # Convert stats dictionary and use list comprehension for efficiency
        return [scores_getter(stats=stats_dict) for stats_dict in stats_dict_list]

    # ******************************************************************** POSTS MANAGEMENT ********************************************************************

    async def create_post(self, user_id: str, post_id: str, data_dict: dict, keep_gt: int = 180, keep_ht: int = 60, keep_ut: int = 60):
        try:
            my_logger.debug(f"data_dict: {data_dict}")

            # Serialize the 'images' list to a JSON string
            if "images" in data_dict and isinstance(data_dict["images"], list):
                data_dict["images"] = json.dumps(data_dict["images"])

            # Add to global timeline if gt not have enough posts
            if await self.redis.zcard(name=self.global_timeline_key) < keep_gt:
                await self.redis.zadd(name=self.global_timeline_key, mapping={post_id: 0})

            # Retrieve followers outside the pipeline
            followers = await self.redis.smembers(f"{self.followers_prefix}{user_id}")

            async with self.redis.pipeline() as pipe:
                # Cache post metadata
                pipe.hset(name=f"{self.post_meta_prefix}{post_id}", mapping=data_dict)

                # Add post to followers home timeline
                for follower_id in followers:
                    pipe.lpush(f"{self.home_timeline_prefix}{follower_id}", post_id)
                    pipe.ltrim(name=f"{self.home_timeline_prefix}{follower_id}", start=0, end=keep_ht)

                # Add post to user timeline
                pipe.lpush(f"{self.user_timeline_prefix}{user_id}", post_id)
                pipe.ltrim(name=f"{self.user_timeline_prefix}{user_id}", start=0, end=keep_ut)

                await pipe.execute()
        except Exception as e:
            my_logger.error(f"Exceptions while creating post: {e}")
            raise ValueError(f"Exceptions while creating post: {e}")

    async def update_post(self, post_id: str, dict_data: dict, keep_gt: int = 180):
        """Update post statistics and recalculate score dynamically."""
        async with self.redis.pipeline() as pipe:
            for key, value in dict_data.items():
                pipe.hset(name=f"{self.post_stats_prefix}{post_id}", key=key, value=value)

            # Fetch all stats
            stats_dict: dict = pipe.hgetall(f"{self.post_stats_prefix}{post_id}")

            # Retrieve timestamp
            created_at: float = pipe.hget(name=f"{self.post_meta_prefix}{post_id}", key="created_at")

            # Calculate new ranking score
            recalculated_score = calculate_score(stats_dict=stats_dict, created_at=created_at)

            # try to add global timeline whatever score is enough to stay global timeline
            pipe.zadd(name=self.global_timeline_key, mapping={post_id: recalculated_score})
            pipe.zremrangebyrank(name=self.global_timeline_key, min=0, max=keep_gt)
            await pipe.execute()

    async def delete_post(self, user_id: str, post_id: str):
        """Completely remove post related things from all places."""
        async with self.redis.pipeline() as pipe:
            # Remove post from global timeline if exists
            pipe.zrem(self.global_timeline_key, post_id)

            # Remove post from all user followers home timelines
            # TODO there is tricky, if when post created user unsubscribe this timeline that post might be exist, also in global timeline
            followers: set[str] = await pipe.smembers(f"{self.followers_prefix}{user_id}")
            for follower_id in followers:
                pipe.lrem(name=f"{self.home_timeline_prefix}{follower_id}", count=0, value=post_id)

            # Remove post from user own timeline
            pipe.lrem(name=f"{self.user_timeline_prefix}{user_id}", count=0, value=post_id)

            # Delete post metadata and stats
            pipe.delete(f"{self.post_meta_prefix}{post_id}", f"{self.post_stats_prefix}{post_id}")

            await pipe.execute()

    # ******************************************************************** FOLLOW MANAGEMENT ********************************************************************

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

    # ***************************************************************** USER PROFILE MANAGEMENT *****************************************************************

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

    # ***************************************************************** USER ACTIONS MANAGEMENT *****************************************************************

    async def mark_post_as_viewed(self, user_id: str, post_id: str):
        await self.redis.hset(name=f"{self.user_event_prefix}{user_id}", key=post_id, value="")

    async def track_user_reaction_to_post(self, user_id: str, post_id: str, reaction: ReactionEnum):
        pass

    async def mark_comment_as_viewed(self, user_id: str, comment_id: str):
        await self.redis.hset(name=f"{self.user_event_prefix}{user_id}", key=comment_id, value="")

    async def track_user_reaction_to_comment(self, user_id: str, comment_id: str, reaction: ReactionEnum):
        pass

    # ****************************************************************** STATISTICS MANAGEMENT ******************************************************************
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

    # ******************************************************** REGISTRATION & FORGOT PASSWORD MANAGEMENT ********************************************************
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
            name=f"{self.forgot_password_prefix}{reset_password_token}",
            mapping={"email": email, "code": code},
        )
        return reset_password_token, (datetime.now() + timedelta(seconds=expiry)).isoformat()

    async def get_reset_password_credentials(self, reset_password_token: str) -> dict:
        """Retrieve password reset credentials."""
        return await self.redis.hgetall(f"{self.forgot_password_prefix}{reset_password_token}")

    async def remove_reset_password_credentials(self, reset_password_token: str):
        """Delete password reset credentials."""
        await self.redis.delete(f"{self.forgot_password_prefix}{reset_password_token}")

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


def scores_getter(stats: dict) -> tuple[int, int, int, int]:
    return stats.get("comments", 0), stats.get("likes", 0), stats.get("dislikes", 0), stats.get("views", 0)


def calculate_score(stats_dict: dict, created_at: float, half_life: float = 36, boost_factor: int = 12) -> float:
    """Calculate post ranking score using weighted metrics and time decay."""
    comments, likes, _, views = scores_getter(stats=stats_dict)
    age_hours = (time.time() - created_at) / 3600

    # Weighted Engagement Score (log-scaled)
    engagement_score = math.log(1 + comments * 5 + likes * 2 + views * 0.5)

    # Exponential Decay (half-life controls decay speed)
    time_decay = math.exp(-age_hours / half_life)

    # Freshness Boost (soft decay instead of sharp drop)
    freshness_boost = 10 * math.exp(-age_hours / boost_factor)

    # Final Score
    return (engagement_score * time_decay) + freshness_boost
