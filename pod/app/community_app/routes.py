import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from tortoise.contrib.pydantic import PydanticModel, pydantic_model_creator

from app.admin_app.routes import ConnectionManager
from app.community_app.models import FollowModel, PostModel, ReactionEnum
from app.community_app.schemas import FollowScheme, PostCreateScheme, PostUpdateSchema
from app.settings.my_dependency import jwtDependency, websocketDependency
from app.settings.my_redis import CacheManager, my_redis
from app.utility.my_logger import my_logger
from app.utility.validators import convert_for_redis

community_router = APIRouter()

PostPydantic = pydantic_model_creator(cls=PostModel)

cache_manager = CacheManager(redis=my_redis)

feed_connection_manager = ConnectionManager()


@community_router.post(path="/follow", status_code=status.HTTP_200_OK)
async def follow_route(follow_schema: FollowScheme, jwt_dependency: jwtDependency):
    try:
        await FollowModel.create(following_id=jwt_dependency.user_id, follower_id=follow_schema.follower_id)
        await cache_manager.add_follower(user_id=jwt_dependency.user_id.hex, follower_id=follow_schema.follower_id.hex)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"ValueError: {e}")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Exception: {e}")


@community_router.post(path="/unfollow", status_code=status.HTTP_200_OK)
async def unfollow_route(follow_schema: FollowScheme, jwt_dependency: jwtDependency):
    try:
        instance = await FollowModel.get_or_none(following_id=jwt_dependency.user_id, follower_id=follow_schema.follower_id)
        if instance is not None:
            await instance.delete()

        await cache_manager.remove_follower(user_id=jwt_dependency.user_id.hex, follower_id=follow_schema.follower_id.hex)

        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"ValueError: {e}")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Exception: {e}")


@community_router.get(path="/followers", status_code=status.HTTP_200_OK)
async def get_followers(jwt_dependency: jwtDependency):
    try:
        return await cache_manager.get_followers(user_id=jwt_dependency.user_id.hex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"ValueError: {e}")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Exception: {e}")


@community_router.get(path="/followings", status_code=status.HTTP_200_OK)
async def get_followings(jwt_dependency: jwtDependency):
    try:
        return await cache_manager.get_following(user_id=jwt_dependency.user_id.hex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"ValueError: {e}")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Exception: {e}")


@community_router.post(path="/posts", status_code=status.HTTP_201_CREATED)
async def create_post(jwt_dependency: jwtDependency, post_create_schema: PostCreateScheme = Depends(PostCreateScheme.as_form)):
    try:
        user_id = jwt_dependency.user_id
        post_create_schema.author_id = user_id.hex
        await post_create_schema.model_async_validate()

        my_logger.debug(f"post_create_schema.video: {post_create_schema.video}; type: {type(post_create_schema.video)}")
        my_logger.debug(f"post_create_schema.images: {post_create_schema.images}; type: {type(post_create_schema.images)}")
        new_post = await PostModel.create(
            author_id=user_id,
            body=post_create_schema.body,
            scheduled_time=post_create_schema.scheduled_time,
            images=post_create_schema.images,
            videos=post_create_schema.video,
        )

        user_avatar_url: Optional[str] = await cache_manager.get_user_avatar_url(user_id=user_id.hex)
        my_logger.debug(f"1 user_avatar_url: {user_avatar_url}")
        if user_avatar_url is not None:
            followers: set[str] = await cache_manager.get_followers(user_id=user_id.hex)
            my_logger.debug(f"2 followers set: {followers}")
            await feed_connection_manager.broadcast(user_ids=list(followers), data={"user_avatar_url": user_avatar_url})

        post_dict = await generate_post_response_from_db_model(db_post=new_post)
        data_dict = convert_for_redis(data=post_dict)
        await cache_manager.create_post(user_id=user_id.hex, post_id=new_post.id.hex, data_dict=data_dict)

        my_logger.debug(f"new_post.video: {new_post.video}; type: {type(new_post.video)}")
        my_logger.debug(f"new_post.images: {new_post.images}; type: {type(new_post.images)}")
        await new_post.delete()

        return {}
    except Exception as e:
        my_logger.critical(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in create_post_route: {e}")


@community_router.get(path="/posts/home_timeline", status_code=status.HTTP_200_OK)
async def get_home_timeline(jwt_dependency: jwtDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_home_timeline(user_id=jwt_dependency.user_id.hex, start=start, end=end)
    except Exception as e:
        my_logger.critical(f"Exception in get_home_timeline_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_home_timeline_route: {e}")


@community_router.get(path="/posts/global_timeline", status_code=status.HTTP_200_OK)
async def get_global_timeline_route(_: jwtDependency, start: int = 0, end: int = 19):
    try:
        return await cache_manager.get_global_timeline(start=start, end=end)
    except ValueError as e:
        print(f"ValueError in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in get_global_timeline: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in get_global_timeline: {e}")


@community_router.post(path="/posts/{post_id}/view", status_code=status.HTTP_200_OK)
async def track_post_view_route(post_id: str, jwt_dependency: jwtDependency):
    try:
        await cache_manager.mark_post_as_viewed(user_id=jwt_dependency.user_id.hex, post_id=post_id)
        return {"status": "post view tracked"}
    except Exception as e:
        print(f"Exception in track_post_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_view_route: {e}")


@community_router.post(path="/posts/{post_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_reaction_route(post_id: str, reaction: ReactionEnum, jwt_dependency: jwtDependency):
    try:
        await cache_manager.track_user_reaction_to_post(user_id=jwt_dependency.user_id.hex, post_id=post_id, reaction=reaction)
        return {"status": "post reaction tracked"}
    except Exception as e:
        print(f"Exception in track_post_reaction_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_reaction_route: {e}")


@community_router.post(path="/comments/{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_comment_view_route(comment_id: str, jwt_dependency: jwtDependency):
    try:
        await cache_manager.mark_comment_as_viewed(user_id=jwt_dependency.user_id.hex, comment_id=comment_id)
        return {"status": "comment view tracked"}
    except Exception as e:
        print(f"Exception in track_post_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_comment_view_route: {e}")


@community_router.post(path="/comments{comment_id}/reaction", status_code=status.HTTP_200_OK)
async def track_post_comment_reaction_route(comment_id: str, reaction: ReactionEnum, jwt_dependency: jwtDependency):
    try:
        await cache_manager.track_user_reaction_to_comment(user_id=jwt_dependency.user_id.hex, comment_id=comment_id, reaction=reaction)
        return {"status": "comment reaction tracked"}
    except Exception as e:
        print(f"Exception in track_post_comment_view_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Exception in track_post_comment_view_route: {e}")


@community_router.patch(path="/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_post_route(post_id: str, post_update_data: PostUpdateSchema, jwt_dependency: jwtDependency):
    try:
        post: Optional[PostModel] = await PostModel.get_or_none(id=post_id)

        if post is None:
            raise ValueError("post not found")

        await post_update_data.model_async_validate()

        updated_post: PostModel = await post.update_from_dict(data=post_update_data.model_dump())

        data_dict: dict = await generate_post_response_from_db_model(db_post=updated_post)  # TODO needed fixes
        await cache_manager.create_post(user_id=jwt_dependency.user_id.hex, post_id=updated_post.id.hex, data_dict=data_dict)
    except ValueError as e:
        print(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating post.")


@community_router.delete(path="/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post_route(post_id: str, jwt_dependency: jwtDependency):
    try:
        post: Optional[PostModel] = await PostModel.get_or_none(id=post_id, author=jwt_dependency.user_id.hex)

        if post is None:
            raise ValueError("post not found")

        await post.delete()

        await cache_manager.delete_post(post_id=post_id, user_id=jwt_dependency.user_id.hex)
        return {"status": "post deleted successfully"}
    except ValueError as e:
        print(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating post.")


@community_router.get(path="/posts/user_timeline", status_code=status.HTTP_200_OK)
async def user_timeline(jwt_dependency: jwtDependency, start: int = 0, end: int = 19):
    try:
        user_timeline_posts: list[dict] = await cache_manager.get_user_timeline(user_id=jwt_dependency.user_id.hex, start=start, end=end)

        if not user_timeline_posts:
            return []

        return user_timeline_posts
    except ValueError as e:
        my_logger.debug(f"ValueError in create_post_route: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        my_logger.debug(f"Exception in user_timeline route: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server error occurred while creating post.")


async def generate_post_response_from_db_model(db_post: PostModel):
    post_pydantic_model: PydanticModel = await PostPydantic.from_tortoise_orm(obj=db_post)
    post_dict = post_pydantic_model.model_dump(exclude_none=True, exclude_defaults=True)

    return post_dict


# ***************************************************************************** WS *****************************************************************************


@community_router.websocket("/ws/new_post_notify")
async def new_post_notify(websocket_dependency: websocketDependency):
    user_id_hex = websocket_dependency.user_id.hex
    websocket: WebSocket = websocket_dependency.websocket

    await feed_connection_manager.connect(websocket=websocket, user_id=user_id_hex)

    try:
        while True:
            await asyncio.sleep(1)
            data: dict = await websocket.receive_json()
            my_logger.debug(f"📨 received_text in new_post_notify data: {data}")
            print(f"Received message from {user_id_hex}: {data}")

    except WebSocketDisconnect:
        feed_connection_manager.disconnect(user_id=user_id_hex)
