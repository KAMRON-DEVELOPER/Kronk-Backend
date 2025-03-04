import json
import math
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Any, Coroutine
from uuid import uuid4

from app.settings.my_config import get_settings
from app.utility.my_enums import ReactionEnum
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

    # ******************************************************************* TIMELINE MANAGEMENT *******************************************************************

    async def get_global_timeline(self, start: int = 0, end: int = 19) -> list[dict]:
        """Get global timeline with post metadata and statistics."""
        gt_post_ids: list[str] = await self.redis.zrevrange(name="global:timeline", start=start, end=end)
        return await self._get_posts(post_ids=gt_post_ids)

    async def get_home_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get home timeline with post metadata, merging user's feed with global timeline."""
        ht_post_ids: list[str] = await self.redis.zrange(name=f"user:{user_id}:home_timeline", start=start, end=end)
        if not ht_post_ids:
            return await self.get_global_timeline(start, end)
        return await self._get_posts(post_ids=ht_post_ids)

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get user timeline posts with stats."""
        ut_post_ids = await self.redis.lrange(name=f"user:{user_id}:timeline", start=start, end=end)
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
            [pipe.hgetall(f"post:{post_id}:meta") for post_id in post_ids]
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
            [pipe.hgetall(f"post:{post_id}:stats") for post_id in post_ids]
            stats_dict_list: list[dict] = await pipe.execute()

        # Convert stats dictionary and use list comprehension for efficiency
        return [scores_getter(stats=stats_dict) for stats_dict in stats_dict_list]

    # ******************************************************************** POSTS MANAGEMENT ********************************************************************

    async def create_post(self, user_id: str, mapping: dict, keep_gt: int = 180, keep_ht: int = 60, keep_ut: int = 60):
        try:
            post_id = mapping["id"]
            # Serialize the 'images' list to a JSON string
            if "images" in mapping and isinstance(mapping["images"], list):
                mapping["images"] = json.dumps(mapping["images"])

            # Retrieve followers outside the pipeline
            followers: set[str] = await self.redis.smembers(f"user:{user_id}:followers")
            my_logger.debug(f"data_dict: {mapping}, followers: {followers}")

            async with self.redis.pipeline() as pipe:
                now = mapping.get("created_at", time.time())

                # Cache post metadata
                pipe.hset(name=f"post:{post_id}:meta", mapping=mapping)

                # Add to global timeline
                await self.redis.zadd(name="global:timeline", mapping={post_id: now})
                pipe.zremrangebyrank(name="global:timeline", min=0, max=-keep_gt - 1)

                # Add post to followers home timeline
                for follower_id in followers:
                    pipe.zadd(name=f"user:{follower_id}:home_timeline", mapping={post_id: now})
                    pipe.zremrangebyrank(name=f"user:{follower_id}:home_timeline", min=0, max=-keep_ht - 1)

                # Add post to user timeline
                pipe.lpush(f"user:{user_id}:timeline", post_id)
                pipe.ltrim(name=f"user:{user_id}:timeline", start=0, end=keep_ut - 1)

                result = await pipe.execute()
                my_logger.debug(f"result: {result}")
        except Exception as e:
            my_logger.error(f"Exceptions while creating post: {e}")
            raise ValueError(f"Exceptions while creating post: {e}")

    async def update_post(self, post_id: str, dict_data: dict, keep_gt: int = 180):
        async with self.redis.pipeline() as pipe:
            for key, value in dict_data.items():
                pipe.hset(name=f"post:{post_id}:stats", key=key, value=value)

            # Fetch all stats
            stats_dict: dict = pipe.hgetall(f"post:{post_id}:stats")

            # Retrieve timestamp
            created_at: float = pipe.hget(name=f"post:{post_id}:meta", key="created_at")

            # Calculate new ranking score
            recalculated_score = calculate_score(stats_dict=stats_dict, created_at=created_at)

            # try to add global timeline whatever score is enough to stay global timeline
            pipe.zadd(name="global:timeline", mapping={post_id: recalculated_score})
            pipe.zremrangebyrank(name="global:timeline", min=0, max=keep_gt)
            await pipe.execute()

    async def delete_post(self, user_id: str, post_id: str):
        followers: set[str] = await self.redis.smembers(f"user:{user_id}:followers")
        my_logger.debug(f"followers: {followers}")

        async with self.redis.pipeline() as pipe:
            # Remove post from global timeline if exists
            pipe.zrem("global:timeline", post_id)

            # Remove post from all user followers home timelines
            for follower_id in followers:
                pipe.zrem(f"user:{follower_id}:home_timeline", post_id)

            # Remove post from user own timeline
            pipe.lrem(name=f"user:{user_id}:timeline", count=0, value=post_id)

            # Delete post metadata and stats
            pipe.delete(f"post:{post_id}:meta", f"post:{post_id}:stats")

            await pipe.execute()

    async def get_posts_count(self):
        return await self.redis.hlen(name="users")  # TODO NEED FIX

    # ***************************************************************** USER PROFILE MANAGEMENT *****************************************************************

    async def create_profile(self, mapping: dict):
        try:
            user_id = mapping["id"]
            async with self.redis.pipeline() as pipe:
                pipe.hset(name=f"user:{user_id}:profile", mapping=mapping)
                pipe.hset(name="usernames", key=mapping["username"], value=user_id)
                pipe.hset(name="emails", key=mapping["email"], value=user_id)
                await pipe.execute()
        except Exception as e:
            raise ValueError(f"🥶 Exception while saving user data to cache: {e}")

    async def update_profile(self, user_id: str, old_username: str, old_email: str, user_data: dict):
        try:
            async with self.redis.pipeline() as pipe:
                pipe.hdel("usernames", old_username)
                pipe.hdel("emails", old_email)

                pipe.hset(name=f"user:{user_id}:meta", mapping=user_data)
                pipe.hset(name="usernames", key=user_data["username"], value=user_id)
                pipe.hset(name="emails", key=user_data["email"], value=user_id)
                await pipe.execute()
        except Exception as e:
            raise ValueError(f"🥶 Exception while updating user data in cache: {e}")

    async def get_profile(self, user_id: str) -> dict:
        return await self.redis.hgetall(f"user:{user_id}:profile")

    async def delete_profile(self, user_id: str, username: str, email: str):
        followers: set[str] = await self.get_followers(user_id)
        following: set[str] = await self.get_following(user_id)

        post_ids: list[str] = await self.redis.lrange(name=f"user:{user_id}:timeline", start=0, end=-1)

        async with my_redis.pipeline() as pipe:
            # Remove user profile
            pipe.hdel(f"user:{user_id}:profile")

            # Remove user timelines
            pipe.hdel(f"user:{user_id}:timeline")
            pipe.hdel(f"user:{user_id}:home_timeline")

            pipe.hdel(f"user:{user_id}:followers")
            pipe.hdel(f"user:{user_id}:followings")

            pipe.hdel("usernames", username)
            pipe.hdel("emails", email)

            # Remove follow relationships
            for follower_id in followers:
                pipe.srem(f"user:{follower_id}:followings", user_id)
            for following_id in following:
                pipe.srem(f"user:{following_id}:followers", user_id)

            # delete all posts created by the user
            for post_id in post_ids:
                pipe.zrem("global:timeline", post_id)

                # Remove post from all user followers home timelines
                for follower_id in followers:
                    pipe.zrem(f"user:{follower_id}:home_timeline", post_id)

                # Delete post metadata and stats
                pipe.delete(f"post:{post_id}:meta", f"post:{post_id}:stats")
            await pipe.execute()

    async def get_profile_by_username(self, username: str) -> dict:
        user_id: Optional[str] = await self.redis.hget(name="usernames", key=username)
        if user_id is None:
            return {}
        return await self.get_profile(user_id=user_id)

    async def get_profile_avatar_url(self, user_id: str) -> Optional[str]:
        return await self.redis.hget(f"user:{user_id}:profile", key="avatar")

    async def is_username_exists(self, username: str) -> bool:
        return await self.redis.hexists(name="usernames", key=username)

    async def is_email_exists(self, email: str) -> bool:
        return await self.redis.hexists(name="emails", key=email)

        # ******************************************************************** FOLLOW MANAGEMENT ********************************************************************

    async def add_follower(self, user_id: str, follower_id: str):
        """Add a follower or multiple followers to the user."""
        async with self.redis.pipeline() as pipe:
            pipe.sadd(f"user:{follower_id}:followers", user_id)
            pipe.sadd(f"user:{user_id}:followings", follower_id)
            await pipe.execute()

    async def remove_follower(self, user_id: str, follower_id: str):
        """Remove a follower relationship."""
        # Get all posts made by the follower
        follower_post_ids: list[str] = await self.redis.lrange(name=f"user:{follower_id}:timeline", start=0, end=-1)

        async with self.redis.pipeline() as pipe:
            # Remove the follower relationship
            pipe.srem(f"user:{user_id}:followings", follower_id)
            pipe.srem(f"user:{follower_id}:followers", user_id)

            if follower_post_ids:
                pipe.zrem(f"user:{user_id}:timeline", *follower_post_ids)
                await pipe.execute()

    async def get_followers(self, user_id: str) -> set[str]:
        """Get all followers of a user."""
        return await self.redis.smembers(f"user:{user_id}:followers")

    async def get_following(self, user_id: str) -> set[str]:
        """Get all users that a user is following."""
        return await self.redis.smembers(f"user:{user_id}:followings")

    async def is_following(self, user_id: str, follower_id: str) -> bool:
        """Check if a user is following another user."""
        return await self.redis.sismember(name=f"user:{user_id}:followings", value=follower_id)

    # ***************************************************************** USER ACTIONS MANAGEMENT *****************************************************************

    async def mark_post_as_viewed(self, user_id: str, post_id: str):
        await self.redis.hset(name=f"user:{user_id}:", key=post_id, value="")

    async def track_user_reaction_to_post(self, user_id: str, post_id: str, reaction: ReactionEnum):
        pass

    async def mark_comment_as_viewed(self, user_id: str, comment_id: str):
        await self.redis.hset(name=f"user:{user_id}:", key=comment_id, value="")

    async def track_user_reaction_to_comment(self, user_id: str, comment_id: str, reaction: ReactionEnum):
        pass

    # ****************************************************************** STATISTICS MANAGEMENT ******************************************************************
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
    async def set_registration_credentials(self, mapping: dict, expiry: int = 600) -> tuple[str, str]:
        verify_token = uuid4().hex
        await self.redis.hset(name=f"registration:{verify_token}", mapping=mapping)
        await self.redis.expire(name=f"registration:{verify_token}", time=expiry)
        return verify_token, (datetime.now() + timedelta(seconds=expiry)).isoformat()

    async def get_registration_credentials(self, verify_token: str) -> dict:
        return await self.redis.hgetall(name=f"registration:{verify_token}")

    async def remove_registration_credentials(self, verify_token: str):
        await self.redis.delete(f"registration:{verify_token}")

    async def set_forgot_password_credentials(self, mapping: dict, expiry: int = 600) -> tuple[str, str]:
        forgot_password_token = uuid4().hex
        await self.redis.hset(name=f"forgot_password:{forgot_password_token}", mapping=mapping)
        await self.redis.expire(name=f"forgot_password:{forgot_password_token}", time=expiry)
        return forgot_password_token, (datetime.now() + timedelta(seconds=expiry)).isoformat()

    async def get_forgot_password_credentials(self, forgot_password_token: str) -> dict:
        return await self.redis.hgetall(f"forgot_password:{forgot_password_token}")

    async def remove_reset_password_credentials(self, forgot_password_token: str):
        await self.redis.delete(f"forgot_password:{forgot_password_token}")

    async def check_registration_existence(self, username: str, email: str):
        registration_keys = await self.redis.keys("registration:*")
        username_exists = False
        email_exists = False

        for key in registration_keys:
            data = await self.redis.hgetall(key)
            if data:
                if data.get("username") == username:
                    username_exists = True
                if data.get("email") == email:
                    email_exists = True
            if username_exists and email_exists:
                break

        return username_exists, email_exists

    # ******************************************************************** HELPER FUNCTIONS ********************************************************************
    async def exists(self, name: str):
        return await self.redis.exists(name)

    # ************************************************************** RESTORATION HELPER FUNCTIONS **************************************************************

    async def get_count(self, match: str, count: int = 1000):
        cursor = 0
        count = 0

        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match=match, count=count)
            count += len(keys)

            if cursor == 0:
                break

        return count

    async def fetch_data_in_batches(self, cursor: int, match: str, limit: int = 1000) -> tuple[int, list[dict]]:
        cursor, keys = await self.redis.scan(cursor=cursor, match=match, count=limit)
        async with self.redis.pipeline() as pipe:
            for key in keys:
                pipe.hgetall(key)
            users = await pipe.execute()

        return cursor, users


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


cache_manager = CacheManager(redis=my_redis)
