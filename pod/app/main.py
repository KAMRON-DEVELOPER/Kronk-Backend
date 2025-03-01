from contextlib import asynccontextmanager

from app.admin_app.routes import admin_router
from app.community_app.routes import community_router
from app.education_app.routes import education_router
from app.my_taskiq.my_taskiq import broker
from app.settings.my_config import get_settings
from app.users_app.models import UserModel
from app.users_app.routes import users_router
from bcrypt import gensalt, hashpw
from faker import Faker
from fastapi import FastAPI
from firebase_admin import initialize_app
from tortoise.contrib.fastapi import register_tortoise

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

# @app.exception_handler(RequestValidationError)
# async def validation_exception_handler(_: Request, exc: RequestValidationError):
#     errors = []
#     for error in exc.errors():
#         field = ".".join(str(loc) for loc in error["loc"])
#         message = error["msg"]
#         errors.append({"field": field, "message": f"{message}"})
#
#     return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": errors})
# details = exc.errors()
# modified_details = []
# for error in details:
#     modified_details.append({"message": error["msg"]})
# return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=jsonable_encoder({"detail": modified_details}))


app.include_router(router=users_router, prefix="/users", tags=["users"])
app.include_router(router=community_router, prefix="/community", tags=["community"])
app.include_router(router=education_router, prefix="/education", tags=["education"])
app.include_router(router=admin_router, prefix="/admin", tags=["admin"])


@app.get(path="/", tags=["root"])
async def root() -> dict:
    await UserModel.bulk_create(
        [
            UserModel(username="alisher", email="alisheratajanov@gmail.com", password=hashpw(password="alisher2009".encode(), salt=gensalt(rounds=8)).decode(), avatar="users/images/alisher.jpg"),
            UserModel(username="kumush", email="kumushatajanova@gmail.com", password=hashpw(password="kumush2010".encode(), salt=gensalt(rounds=8)).decode(), avatar="users/images/kumush.jpg"),
            UserModel(username="ravshan", email="yangiboyevravshan@gmail.com", password=hashpw(password="ravshan2004".encode(), salt=gensalt(rounds=8)).decode(), avatar="users/images/ravshan.jpeg"),
        ]
    )
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
