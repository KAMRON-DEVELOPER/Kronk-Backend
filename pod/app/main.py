from contextlib import asynccontextmanager

from app.admin_app.routes import admin_router
from app.community_app.routes import community_router
from app.education_app.routes import education_router
from app.my_taskiq.my_taskiq import broker
from app.settings.my_config import get_settings
from app.users_app.routes import users_router
from faker import Faker
from fastapi import FastAPI
from firebase_admin import initialize_app
from tortoise.contrib.fastapi import register_tortoise

from app.users_app.models import UserModel

settings = get_settings()

fake = Faker()


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
    return {"status": "ok"}


try:
    register_tortoise(app=app, config=get_settings().get_tortoise_orm(), generate_schemas=True, add_exception_handlers=True)
except Exception as e:
    print(f"tortoise setup error: {e}")

try:
    initialize_app(settings.get_firebase_credentials())
except Exception as exception:
    print(f"firebase initialization error: {exception}")


@app.get(path="/create_test_users", tags=["create_test_users"])
async def create_test_users() -> dict:
    fake_users = []

    for i in range(1, 201):
        avatar = f"users/images/avatar_1{i}.png" if i <= 175 else None
        user = UserModel(
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            username=f"{fake.user_name()}{i}",  # Ensure uniqueness
            email=f"{fake.email().split('@')[0]}{i}@example.com",
            password="$2b$12$saltsaltsaltsaltstring",
            avatar=avatar,
            banner=None,
            banner_color=fake.hex_color().lstrip("#"),
            birthdate=fake.date_of_birth(minimum_age=16, maximum_age=45).isoformat(),
            bio=fake.sentence(),
            country=fake.country(),
        )
        fake_users.append(user)

    await UserModel.bulk_create(objects=fake_users, batch_size=20)
    return {"status": "ok"}
