from typing import Optional, Annotated

from app.admin_app.routes import ConnectionManager
from app.community_app.models import PostModel, ReactionEnum
from app.community_app.schemas import PostCreateScheme, PostUpdateSchema
from app.settings.my_dependency import jwtAccessDependency, websocketDependency
from app.settings.my_redis import CacheManager, my_redis
from app.utility.my_logger import my_logger
from fastapi import APIRouter, HTTPException, status, WebSocketException
from tortoise.contrib.pydantic import PydanticModel, pydantic_model_creator
from fastapi import WebSocket, WebSocketDisconnect, Query, Header

community_router = APIRouter()

PostPydantic = pydantic_model_creator(cls=PostModel)

cache_manager = CacheManager(redis=my_redis)

feed_connection_manager = ConnectionManager()


@community_router.post(path="/posts", status_code=status.HTTP_201_CREATED)
async def create_post(post_create_schema: PostCreateScheme, jwt_access_dependency: jwtAccessDependency):
    try:
        user_id = jwt_access_dependency.subject["id"]
        await post_create_schema.model_async_validate()

        new_post = await PostModel.create(
            author=user_id,
            body=post_create_schema.body,
            scheduled_time=post_create_schema.scheduled_time,
            images=post_create_schema.images,
            videos=post_create_schema.video,
        )

        await cache_manager.create_post(user_id=user_id, new_post=new_post)

        user_avatar_url: Optional[str] = (await cache_manager.get_user_profile(user_id=user_id)).get("avatar")
        if user_avatar_url is not None:
            followers: set[str] = await cache_manager.get_followers(user_id=user_id)
            await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})

        return await generate_post_response(db_post=new_post)
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exception in create_post_route: {e}")


@community_router.get(path="/posts/home_timeline", status_code=status.HTTP_200_OK)
async def get_home_timeline(jwt_access_dependency: jwtAccessDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_home_timeline(user_id=jwt_access_dependency.subject["id"], start=start, end=end)
    except Exception as e:
        print(f"Exception in get_home_timeline_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_home_timeline_route: {e}")


@community_router.get(path="/posts/global_timeline", status_code=status.HTTP_200_OK)
async def get_global_timeline_route(_: jwtAccessDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_global_timeline(start=start, end=end)
    except ValueError as e:
        print(f"ValueError in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
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


@community_router.get(path="/posts/user_timeline", status_code=status.HTTP_200_OK)
async def user_timeline(jwt_access_dependency: jwtAccessDependency, start: int = 0, end: int = 19):
    try:
        user_timeline_posts: list[dict] = await cache_manager.get_user_timeline(user_id=jwt_access_dependency.subject["id"], start=start, end=end)

        if not user_timeline_posts:
            return []

        return user_timeline_posts
    except ValueError as e:
        my_logger.debug(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        my_logger.debug(f"Exception in user_timeline route: {e}")
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


# ************************************************** WS **************************************************


async def get_token(websocket: WebSocket, token: Annotated[str | None, Query()] = None):
    if token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return token


async def get_header_token(websocket: WebSocket, authorization: Annotated[str | None, Header()] = None):
    if authorization is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return authorization


@community_router.websocket('/ws/new_post_notify')
async def new_post_notify(user_ws: websocketDependency):
    user_id: str = user_ws.user_id
    websocket: WebSocket = user_ws.websocket
    await feed_connection_manager.connect(websocket=websocket, user_id=user_id)

    try:
        while True:
            data = await websocket.receive_text()
            my_logger.info(f"📨 received_text in new_post_notify data: {data}")
    except WebSocketDisconnect:
        feed_connection_manager.disconnect(user_id=user_id)
