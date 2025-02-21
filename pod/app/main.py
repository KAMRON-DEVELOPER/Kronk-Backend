from contextlib import asynccontextmanager

from app.admin_app.routes import admin_router
from app.community_app.routes import community_router
from app.education_app.routes import education_router
from app.my_taskiq.my_taskiq import broker
from app.utility.my_logger import my_logger
from app.users_app.routes import users_router
from fastapi import FastAPI
from firebase_admin import initialize_app
from tortoise.contrib.fastapi import register_tortoise
from app.settings.my_config import get_settings
from app.settings.my_redis import my_redis

settings = get_settings()


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    if not broker.is_worker_process:
        await broker.startup()
    yield
    if not broker.is_worker_process:
        await broker.shutdown()


app: FastAPI = FastAPI(lifespan=app_lifespan)

app.include_router(router=users_router, prefix="/users", tags=["users"])
app.include_router(router=community_router, prefix="/community", tags=["community"])
app.include_router(router=education_router, prefix="/education", tags=["education"])
app.include_router(router=admin_router, prefix="/admin", tags=["admin"])


@app.get(path="/", tags=["root"])
async def root() -> dict:
    async with my_redis.pipeline() as pipe:
        pipe.hget(name="names", key="kamronbek")
        pipe.hget(name="names", key="adhambek")
        pipe.hget(name="names", key="alisher")
        result = await pipe.execute()

    async with my_redis.pipeline() as pipe:
        pipe.hget(name="names", key="kamronbek").hget(name="names", key="adhambek").hget(name="names", key="alisher")
        regular_result = await pipe.execute()

    async with my_redis.pipeline() as pipe:
        [pipe.hget(name="names", key=username) for username in ["kamronbek", "adhambek", "alisher"]]
        post_dict_list = await pipe.execute()

    my_logger.trace(f"result: {result}. type: {type(result)}")
    my_logger.trace(f"regular_result: {result}. type: {type(regular_result)}")
    my_logger.trace(f"post_dict_list: {post_dict_list}. type: {type(post_dict_list)}")
    return {"status": "ok", "result": result, "regular_result": regular_result, "post_dict_list": post_dict_list}


try:
    register_tortoise(app=app, config=get_settings().get_tortoise_orm(), generate_schemas=True, add_exception_handlers=True)
except Exception as e:
    print(f"tortoise setup error: {e}")

try:
    initialize_app(settings.get_firebase_credentials())
except Exception as exception:
    print(f"firebase initialization error: {exception}")
