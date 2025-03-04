from typing import Iterable, Optional

from app.settings.my_minio import remove_objects_from_minio
from app.settings.my_redis import cache_manager
from app.users_app.models import BaseModel, UserModel
from app.utility.my_enums import ReactionEnum
from app.utility.my_logger import my_logger
from tortoise import BaseDBAsyncClient, fields


class FollowModel(BaseModel):
    follower: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="followings", to_field="id")
    following: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="followers", to_field="id")

    class Meta:
        table = "follow"
        unique_together = ("follower", "following")

    async def save(
        self,
        using_db: Optional[BaseDBAsyncClient] = None,
        update_fields: Optional[Iterable[str]] = None,
        force_create: bool = False,
        force_update: bool = False,
    ) -> None:
        if self.follower.username == self.following.username:
            raise ValueError("Users cannot follow themselves.")
        await super().save(using_db=using_db, update_fields=update_fields, force_create=force_create, force_update=force_update)

    async def delete(self, using_db: Optional[BaseDBAsyncClient] = None) -> None:
        try:
            await cache_manager.remove_follower(user_id=self.following, follower_id=self.follower)
        except Exception as exception:
            my_logger.error(f"🚧 Could not remove follow relationship in cache. detail: {exception}")
            raise ValueError(f"🚧 Could not remove follow relationship in cache. detail: {exception}")

    def __str__(self):
        return "🚧 FollowModel"


class PostModel(BaseModel):
    author: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="posts", to_field="id")
    body = fields.CharField(max_length=200)
    images = fields.JSONField(null=True)
    video = fields.CharField(max_length=255, null=True)
    scheduled_time = fields.DatetimeField(null=True)
    is_archived = fields.BooleanField(default=False)

    # Engagement Metrics
    comments_count = fields.IntField(default=0)
    likes_count = fields.IntField(default=0)
    dislikes_count = fields.IntField(default=0)
    views_count = fields.IntField(default=0)

    # Reverse relations
    post_comments: fields.ReverseRelation["PostCommentModel"]
    post_reactions: fields.ReverseRelation["PostReactionModel"]
    post_views: fields.ReverseRelation["PostViewModel"]

    class Meta:
        table = "post"

    class PydanticMeta:
        allow_cycles = True

    async def delete(self, using_db: Optional[BaseDBAsyncClient] = None) -> None:
        try:
            # delete media of the post
            if self.video:
                my_logger.debug(f"PostModel deleting video: {self.video}")
                await remove_objects_from_minio(object_names=[self.video])
            if self.images:
                my_logger.debug(f"PostModel deleting images: {self.images}")
                await remove_objects_from_minio(object_names=self.images)

            # comments = self.post_comments.all()
            # if comments:
            #     await comments.delete()

            # reactions = self.post_reactions.all()
            # if reactions:
            #     await reactions.delete()

            # views = self.post_views.all()
            # if views:
            #     await views.delete()
            await super().delete(using_db=using_db)
        except Exception as exception:
            my_logger.error(f"🚧 Could not delete post media. detail: {exception}")
            raise ValueError(f"🚧 Could not delete post media. detail: {exception}")

    def __str__(self):
        return "🚧 PostModel"


class PostCommentModel(BaseModel):
    user: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="post_comments", to_field="id")
    post: fields.ForeignKeyRelation["PostModel"] = fields.ForeignKeyField(model_name="community_app.PostModel", related_name="post_comments", to_field="id")
    parent: fields.ForeignKeyNullableRelation["PostCommentModel"] = fields.ForeignKeyField(model_name="community_app.PostCommentModel", null=True, related_name="replies", to_field="id")
    body = fields.CharField(max_length=200)
    image = fields.CharField(max_length=255, null=True)
    video = fields.CharField(max_length=255, null=True)

    # Engagement Metrics
    comments_count = fields.IntField(default=0)
    likes_count = fields.IntField(default=0)
    dislikes_count = fields.IntField(default=0)
    views_count = fields.IntField(default=0)

    # Reverse relations
    post_comment_reactions: fields.ReverseRelation["PostCommentReactionModel"]
    post_comment_views: fields.ReverseRelation["PostCommentViewModel"]

    class Meta:
        table = "post_comment"

    def __str__(self):
        return "🚧 PostCommentModel"


class PostReactionModel(BaseModel):
    user: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="post_reactions", to_field="id")
    post: fields.ForeignKeyRelation["PostModel"] = fields.ForeignKeyField(model_name="community_app.PostModel", related_name="post_reactions", to_field="id")
    reaction = fields.CharEnumField(enum_type=ReactionEnum)

    class Meta:
        table = "post_reaction"
        unique_together = ("user", "post")

    def __str__(self):
        return "🚧 PostReactionModel"


class PostCommentReactionModel(BaseModel):
    user: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="post_comment_reactions", to_field="id")
    post_comment: fields.ForeignKeyRelation["PostCommentModel"] = fields.ForeignKeyField(model_name="community_app.PostCommentModel", related_name="post_comment_reactions", to_field="id")
    reaction = fields.CharEnumField(enum_type=ReactionEnum)

    class Meta:
        table = "post_comment_reaction"
        unique_together = ("user", "post_comment")

    def __str__(self):
        return "🚧 PostCommentReactionModel"


class PostViewModel(BaseModel):
    user: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="post_views", to_field="id")
    post: fields.ForeignKeyRelation["PostModel"] = fields.ForeignKeyField(model_name="community_app.PostModel", related_name="post_views", to_field="id")

    class Meta:
        table = "post_view"
        unique_together = ("user", "post")

    def __str__(self):
        return "🚧 PostViewModel"


class PostCommentViewModel(BaseModel):
    user: fields.ForeignKeyRelation["UserModel"] = fields.ForeignKeyField(model_name="users_app.UserModel", related_name="post_comment_views", to_field="id")
    post_comment: fields.ForeignKeyRelation["PostCommentModel"] = fields.ForeignKeyField(model_name="community_app.PostCommentModel", related_name="post_comment_views", to_field="id")

    class Meta:
        table = "post_comment_view"
        unique_together = ("user", "post_comment")

    def __str__(self):
        return "🚧 PostCommentViewModel"
