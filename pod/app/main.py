from contextlib import asynccontextmanager

from app.admin_app.routes import admin_router
from app.community_app.routes import community_router
from app.education_app.routes import education_router
from app.my_taskiq.my_taskiq import broker
from app.settings.my_config import get_settings
from app.users_app.routes import users_router
from fastapi import FastAPI
from firebase_admin import initialize_app
from tortoise.contrib.fastapi import register_tortoise

settings = get_settings()


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    """Manages startup and shutdown processes."""
    try:
        initialize_app(settings.get_firebase_credentials())
    except Exception as exception:
        print(f"firebase initialization error: {exception}")

    if not broker.is_worker_process:
        print("🗓️ Starting...")
        await broker.startup()

    yield

    if not broker.is_worker_process:
        print("🗓️ Shutting down...")
        await broker.shutdown()


app: FastAPI = FastAPI(lifespan=app_lifespan)

try:
    register_tortoise(app=app, config=get_settings().get_tortoise_orm(), generate_schemas=True, add_exception_handlers=True)
except Exception as e:
    print(f"tortoise setup error: {e}")

app.include_router(router=users_router, prefix="/users", tags=["users"])
app.include_router(router=community_router, prefix="/community", tags=["community"])
app.include_router(router=education_router, prefix="/education", tags=["education"])
app.include_router(router=admin_router, prefix="/admin", tags=["admin"])


@app.get(path="/", tags=["root"])
async def root() -> dict:
    return {"status": "ok"}
