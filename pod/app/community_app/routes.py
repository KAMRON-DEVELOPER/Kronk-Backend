from typing import Optional

from fastapi import APIRouter, HTTPException, status
from tortoise.contrib.pydantic import PydanticModel, pydantic_model_creator

from app.community_app.models import PostModel, ReactionEnum
from app.community_app.schemas import PostCreateScheme, PostUpdateSchema
from app.settings.my_dependency import jwtAccessDependency
from app.settings.my_redis import CacheManager, my_redis

community_router = APIRouter()

PostPydantic = pydantic_model_creator(cls=PostModel)

cache_manager = CacheManager(redis=my_redis)


@community_router.post(path="/posts", status_code=status.HTTP_201_CREATED)
async def create_post(post_create_schema: PostCreateScheme, credentials: jwtAccessDependency):
    try:
        await post_create_schema.model_async_validate()

        new_post = await PostModel.create(
            author=credentials.subject["id"],
            body=post_create_schema.body,
            scheduled_time=post_create_schema.scheduled_time,
            images=post_create_schema.images,
            videos=post_create_schema.video,
        )

        await cache_manager.create_post(user_id=credentials["id"], new_post=new_post)

        return await generate_post_response(db_post=new_post)
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exception in create_post_route: {e}")


@community_router.get(path="/posts/home_timeline", status_code=status.HTTP_200_OK)
async def get_home_timeline(credentials: jwtAccessDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_home_timeline(user_id=credentials.subject["id"], start=start, end=end)
    except Exception as e:
        print(f"Exception in get_home_timeline_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_home_timeline_route: {e}")


@community_router.get(path="/posts/global_timeline", status_code=status.HTTP_200_OK)
async def get_global_timeline_route(_: jwtAccessDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_global_timeline(start=start, end=end)
    except Exception as e:
        print(f"Exception in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_global_timeline: {e}")


@community_router.post(path="/posts/{post_id}/view", status_code=status.HTTP_200_OK)
async def track_post_view_route(post_id: str, credentials: jwtAccessDependency):
    try:
        await cache_manager.mark_post_as_viewed(user_id=credentials["id"], post_id=post_id)
        return {"status": "post view tracked"}
    except Exception as e:
        print(f"Exception in track_post_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_view_route: {e}")


@community_router.post(path="/posts/{post_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_reaction_route(post_id: str, reaction: ReactionEnum, credentials: jwtAccessDependency):
    try:
        await cache_manager.track_user_reaction_to_post(user_id=credentials["id"], post_id=post_id, reaction=reaction)
        return {"status": "post reaction tracked"}
    except Exception as e:
        print(f"Exception in track_post_reaction_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_reaction_route: {e}")


@community_router.post(path="/comments/{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_comment_view_route(comment_id: str, credentials: jwtAccessDependency):
    try:
        await cache_manager.mark_comment_as_viewed(user_id=credentials["id"], comment_id=comment_id)
        return {"status": "comment view tracked"}
    except Exception as e:
        print(f"Exception in track_post_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_comment_view_route: {e}")


@community_router.post(path="/comments{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_comment_reaction_route(comment_id: str, reaction: ReactionEnum, credentials: jwtAccessDependency):
    try:
        await cache_manager.track_user_reaction_to_comment(user_id=credentials["id"], comment_id=comment_id, reaction=reaction)
        return {"status": "comment reaction tracked"}
    except Exception as e:
        print(f"Exception in track_post_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_comment_view_route: {e}")


@community_router.patch(path="/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_post_route(post_id: str, post_update_data: PostUpdateSchema, credentials: jwtAccessDependency):
    try:
        post: Optional[PostModel] = await PostModel.get_or_none(id=post_id)

        if post is None:
            raise ValueError("post not found")

        await post_update_data.model_async_validate()

        updated_post: PostModel = await post.update_from_dict(data=post_update_data.model_dump())

        await cache_manager.create_post(new_post=updated_post, user_id=credentials["id"])
    except ValueError as e:
        print(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating post.")


@community_router.delete(path="/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post_route(post_id: str, credentials: jwtAccessDependency):
    try:
        post: Optional[PostModel] = await PostModel.get_or_none(id=post_id, author=credentials["id"])

        if post is None:
            raise ValueError("post not found")

        await post.delete()

        await cache_manager.delete_post(post_id=post_id, user_id=credentials["id"])
        return {"status": "post deleted successfully"}
    except ValueError as e:
        print(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating post.")


async def generate_post_response(db_post: PostModel):
    post_pydantic_model: PydanticModel = await PostPydantic.from_tortoise_orm(obj=db_post)

    post_dict = post_pydantic_model.model_dump(exclude_none=False)
    comments_count = await db_post.post_comments.all().count()
    likes_count = await db_post.post_reactions.filter(reaction=ReactionEnum.LIKE).all().count()
    dislikes_count = await db_post.post_reactions.filter(reaction=ReactionEnum.DISLIKE).all().count()
    views_count = await db_post.post_views.all().count()
    # print(f"🚧 post_dict: {post_dict}")

    return {**post_dict, "comments_count": comments_count, "likes_count": likes_count, "dislikes_count": dislikes_count, "views_count": views_count}
