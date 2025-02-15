import math
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4, UUID

from redis.asyncio import Redis

from app.community_app.models import PostModel, ReactionEnum
from app.settings.my_config import get_settings
from app.users_app.models import UserModel

my_redis = Redis.from_url(url=get_settings().REDIS_URL, decode_responses=True, auto_close_connection_pool=True)


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
        self.following_prefix = "following:"
        self.user_profile_prefix = "user_profile:"
        self.user_event_prefix = "user_event:"
        self.register_prefix = "register:"
        self.reset_password_prefix = "reset_password:"

    ## ---------------------------------------- TIMELINE MANAGEMENT ----------------------------------------
    async def _add_post_to_gt(self, post_id: str, amount: int = 180):
        """Add post ID to global timeline and keep only the latest amount of posts."""
        await self.redis.hset(name=f"{self.post_timestamp_key}", key=f"{post_id}", value=f"{int(time.time())}")
        if await self.redis.zcard(name=f"{self.global_timeline_key}") < amount:
            await self.redis.zadd(name=self.global_timeline_key, mapping={post_id: 0})

    async def get_global_timeline(self, start: int = 0, end: int = 19) -> list[dict]:
        """Get global timeline with post metadata and statistics."""
        gt_post_ids: list[bytes] = await self.redis.zrevrange(name=self.global_timeline_key, start=start, end=end)
        if not gt_post_ids:
            return []

        gt_posts = await self._get_posts(post_ids=gt_post_ids)
        return gt_posts

    async def add_post_to_ht(self, user_id: str, post_id: str, start: int = 0, end: int = 59):
        """Add post to home timeline and trim in specified range"""
        await self.redis.lpush(f"{self.home_timeline_prefix}{user_id}", post_id)
        await self.redis.ltrim(name=f"{self.home_timeline_prefix}{user_id}", start=start, end=end)

    async def get_home_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get home timeline with post metadata, merging user's feed with global timeline."""
        ht_post_ids: list[bytes] = await self.redis.lrange(name=f"{self.home_timeline_prefix}{user_id}", start=start, end=end)

        if not ht_post_ids:
            # If home timeline is empty, return empty list(fall back to global timeline)
            return await self.get_global_timeline(start, end)

        home_posts = await self._get_posts(post_ids=ht_post_ids)
        return home_posts

    async def add_post_to_ut(self, user_id: str, post_id: str, start: int = 0, end: int = 4000):
        """Push post ID to user timeline in Redis List."""
        await self.redis.lpush(f"{self.user_timeline_prefix}{user_id}", post_id)
        await self.redis.ltrim(name=f"{self.user_timeline_prefix}{user_id}", start=start, end=end)

    async def get_user_timeline(self, user_id: str, start: int = 0, end: int = 19) -> list[dict]:
        """Get user posts"""
        return await self.redis.lrange(name=f"{self.user_timeline_prefix}{user_id}", start=start, end=end)

    async def get_single_post(self, post_id: str) -> dict:
        """Get single post with given specific post id."""
        posts = await self._get_posts(post_ids=[post_id.encode()])
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

    async def _get_post_stats(self, post_id: str) -> tuple[int, int, int, int, int, int]:
        """Get post statistics as a tuple (comments, reposts, quotes, likes, dislikes, views)."""
        stats_dict_bytes = await self.redis.hgetall(f"{self.post_stats_prefix}{post_id}")
        stats = {k.decode(): int(v.decode()) for k, v in stats_dict_bytes.items()} if stats_dict_bytes else {}
        return scores_getter(stats=stats)

    async def _get_posts(self, post_ids: list[bytes]):
        async with self.redis.pipeline() as pipe:
            # Fetch post metadata
            for post_id in post_ids:
                await pipe.hgetall(f"{self.post_meta_prefix}{post_id.decode()}")
            post_meta_bytes_list = await pipe.execute()

        # Decode metadata
        posts = [meta_bytes for meta_bytes in post_meta_bytes_list]

        # Fetch post stats
        for post, post_id in zip(posts, post_ids):
            stat = await self._get_post_stats(post_id.decode())
            post.update({"comments": stat[0], "reposts": stat[1], "quotes": stat[2], "likes": stat[3], "dislikes": stat[4], "views": stat[5]})

        return posts

    ## ---------------------------------------- POSTS MANAGEMENT ----------------------------------------

    async def create_post(self, user_id: str, new_post: PostModel):
        post_mapping = {"id": new_post.id, "author": user_id, "body": new_post.body, "images": new_post.images or "", "video": new_post.video or ""}
        await self.redis.hset(name=f"{self.post_meta_prefix}{new_post.id}", mapping={k: v for k, v in post_mapping.items() if v})

        # Add to global timeline
        await self._add_post_to_gt(post_id=str(new_post.id))

        followers = await self.get_followers(user_id=user_id)
        for follower_id in followers:
            await self.add_post_to_ht(user_id=follower_id, post_id=str(new_post.id))

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
        """Add a follower relationship (follower_id follows user_id)."""
        await self.redis.sadd(f"{self.followers_prefix}{user_id}", follower_id)
        await self.redis.sadd(f"{self.following_prefix}{follower_id}", user_id)

    async def remove_follower(self, user_id: str, follower_id: str):
        """Remove a follower relationship."""
        await self.redis.srem(f"{self.followers_prefix}{user_id}", follower_id)
        await self.redis.srem(f"{self.following_prefix}{follower_id}", user_id)

    async def get_followers(self, user_id: str) -> set[str]:
        """Get all followers of a user."""
        return await self.redis.smembers(f"{self.followers_prefix}{user_id}")

    async def get_following(self, user_id: str) -> set[str]:
        """Get all users that a user follows."""
        return await self.redis.smembers(f"{self.following_prefix}{user_id}")

    ## ---------------------------------------- USER PROFILE MANAGEMENT ----------------------------------------
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
                print(f"🚧 mapping: {user_mapping}")
                await (
                    pipe.hset(name=f"{self.user_profile_prefix}{new_user.id.hex}", mapping=user_mapping)
                    .sadd("user_profiles", new_user.id.hex)
                    .hset(name="usernames", mapping={new_user.username: new_user.id.hex})
                    .hset(name="emails", mapping={new_user.email: "1"})
                    .execute()
                )
        except Exception as e:
            raise ValueError(f"🥶 Exception in create_user_profile: {e}")

    async def get_user_profile(self, user_id: str) -> dict:
        """Retrieve user profile details."""
        profile_dict = await self.redis.hgetall(f"{self.user_profile_prefix}{user_id}")
        return {k: v for k, v in profile_dict.items()} if profile_dict else {}

    async def get_user_profile_by_username(self, username: str) -> dict:
        user_id: Optional[str] = await self.redis.hget(name="usernames", key=username)
        return await self.get_user_profile(user_id=user_id)

    async def delete_user_profile(self, user_id: str):
        """Delete a user profile and associated data."""

        pipe = self.redis.pipeline()

        # Remove follow relationships
        followers: set[str] = await self.get_followers(user_id)
        following: set[str] = await self.get_following(user_id)

        for follower_id in followers:
            await pipe.srem(f"{self.following_prefix}{follower_id}", user_id)

        for followed_id in following:
            await pipe.srem(f"{self.followers_prefix}{followed_id}", user_id)

        # Delete user profile and all related keys
        await pipe.delete(
            f"{self.home_timeline_prefix}{user_id}",
            f"{self.user_timeline_prefix}{user_id}",
            f"{self.user_profile_prefix}{user_id}",
            f"{self.followers_prefix}{user_id}",
            f"{self.following_prefix}{user_id}",
        )

        await pipe.execute()

        post_ids: list[str] = await self.redis.lrange(name=f"{self.user_timeline_prefix}{user_id}", start=0, end=-1)
        for post_id in post_ids:
            await self.delete_post(post_id, user_id)

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
        return await self.redis.scard("usernames")

    async def exists(self, name: str):
        return await self.redis.exists(name)

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
