from io import BytesIO
from random import randint
from typing import Optional

from app.my_taskiq.my_taskiq import broadcast_stats_to_settings_task, send_email_task
from app.services.firebase_service import validate_firebase_token
from app.settings.my_dependency import headerTokenDependency, jwtAccessDependency, jwtRefreshDependency
from app.settings.my_minio import put_object_to_minio, remove_object_from_minio, wipe_objects_from_minio
from app.settings.my_redis import CacheManager, my_redis
from app.users_app.models import UserModel
from app.users_app.schemas import LoginSchema, RegisterSchema, RequestResetPasswordSchema, ResetPasswordSchema, UpdateSchema, VerifySchema
from app.utility.my_logger import my_logger
from app.utility.utility import generate_avatar_url, generate_password_string, generate_unique_username
from app.utility.validators import allowed_image_extension, get_file_extension, validate_password
from bcrypt import checkpw, gensalt, hashpw
from fastapi import APIRouter, HTTPException, status
from firebase_admin.auth import UserRecord
from tortoise.contrib.pydantic import PydanticModel, pydantic_model_creator
from app.utility.jwt_utils import create_access_token, create_refresh_token

users_router = APIRouter()

UserProfilePydantic = pydantic_model_creator(cls=UserModel)

cache_manager = CacheManager(redis=my_redis)


@users_router.post(path="/register", status_code=status.HTTP_201_CREATED)
async def register(register_schema: RegisterSchema, header_token_dependency: headerTokenDependency):
    try:
        if header_token_dependency.verify_token and await cache_manager.exists(name=header_token_dependency.verify_token):
            raise ValueError("Check your email! Your verification token is on its way.")

        await register_schema.model_async_validate()

        is_username_exist, is_email_exist = await cache_manager.is_someone_registering_with_this_username_and_email(
            username=register_schema.username,
            email=register_schema.email,
        )
        if is_username_exist:
            raise ValueError("Someone is already registering with this username.")
        if is_email_exist:
            raise ValueError("Someone is already registering with this email.")

        is_username_exist_already, is_email_exist_already = await cache_manager.is_user_already_exist_with_this_username_and_email(
            username=register_schema.username,
            email=register_schema.email,
        )
        if is_username_exist_already:
            raise ValueError("Username already exists.")
        if is_email_exist_already:
            raise ValueError("Email already exists.")

        code = "".join([str(randint(a=0, b=9)) for _ in range(4)])
        verify_token, verify_token_expiration_date = await cache_manager.set_registration_credentials(
            username=register_schema.username,
            email=register_schema.email,
            password=register_schema.password,
            code=code,
        )

        await send_email_task.kiq(to_email=register_schema.email, username=register_schema.username, code=code)

        return {"verify_token": verify_token, "verify_token_expiration_date": verify_token_expiration_date}

    except ValueError as e:
        print(f"ValueError in register_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e} ")
    except Exception as e:
        print(f"Exception in register_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="🌋 Oops! Something went wrong on our side while signing you up. Try again soon!")


@users_router.post(path="/verify", status_code=status.HTTP_200_OK)
async def verify_user(verify_schema: VerifySchema, header_token_dependency: headerTokenDependency):
    try:
        if header_token_dependency.verify_token is None:
            raise ValueError("Your verification token is missing.")

        registration_data: dict = await cache_manager.get_registration_credentials(verify_token=header_token_dependency.verify_token)
        if not registration_data:
            raise ValueError("Your verify token was not found.")

        await verify_schema.model_async_validate()

        if verify_schema.code != registration_data.get("code"):
            raise ValueError("Your verification code is incorrect.")

        new_user: UserModel = await UserModel.create(
            username=registration_data.get("username"),
            email=registration_data.get("email"),
            password=hashpw(password=registration_data.get("password", "").encode(), salt=gensalt(rounds=8)).decode(),
        )

        await cache_manager.create_user_profile(new_user=new_user)
        await cache_manager.remove_registration_credentials(verify_token=header_token_dependency.verify_token)

        await broadcast_stats_to_settings_task.kiq()

        return generate_token_response(user_id=new_user.id.hex)
    except ValueError as e:
        print(f"ValueError in verify_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in verify_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="🌋 Oops! Something went wrong on our side while verifying you. Try again soon!")


@users_router.post(path="/login", status_code=status.HTTP_200_OK)
async def login_user(login_schema: LoginSchema):
    try:
        await login_schema.model_async_validate()
        if login_schema.username is None or login_schema.password is None:
            return

        user_data: dict = await cache_manager.get_user_profile_by_username(username=login_schema.username)
        if user_data:
            if not checkpw(login_schema.password.encode(), f"{user_data.get("password")}".encode()):
                raise ValueError("password is not match.")

            return user_data

        db_user: Optional[UserModel] = await UserModel.get_or_none(username=login_schema.username)
        if not db_user:
            raise ValueError("User not found.")

        if not checkpw(login_schema.password.encode(), db_user.password.encode()):
            raise ValueError("password is not match.")

        await cache_manager.create_user_profile(new_user=db_user)

        return generate_token_response(user_id=db_user.id.hex)
    except ValueError as e:
        print(f"ValueError in login_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in login_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="🌋 Oops! Something went wrong on our side while logging you in. Try again soon!")


@users_router.post(path="/logout", status_code=status.HTTP_200_OK)
async def logout(jwt_access_dependency: jwtAccessDependency):
    try:
        db_user: Optional[UserModel] = await UserModel.get_or_none(id=jwt_access_dependency.user_id)
        if not db_user:
            return {}

        await cache_manager.delete_user_profile(user_id=jwt_access_dependency.user_id, username=db_user.username, email=db_user.email)
        return {}
    except ValueError as e:
        print(f"ValueError in login_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in login_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="🌋 Oops! Something went wrong on our side while logging you in. Try again soon!")


@users_router.post(path="/request-reset-password", status_code=status.HTTP_200_OK)
async def request_reset_password(request_reset_password_schema: RequestResetPasswordSchema):
    try:
        await request_reset_password_schema.model_async_validate()

        db_user: Optional[UserModel] = await UserModel.get_or_none(email=request_reset_password_schema.email)
        if not db_user:
            raise ValueError("No user found with this email.")

        code: str = "".join([str(randint(a=0, b=9)) for _ in range(4)])
        reset_password_token, reset_password_token_expiration_date = await cache_manager.set_reset_password_credentials(
            email=request_reset_password_schema.email,
            code=code,
        )

        await send_email_task.kiq(to_email=request_reset_password_schema.email, username=db_user.username, code=code, for_reset_password=True)

        return {"reset_password_token": reset_password_token, "reset_password_token_expiration_date": reset_password_token_expiration_date}
    except ValueError as e:
        print(f"ValueError in request_reset_password: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in request_reset_password: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="🌋 Oops! Something went wrong on our side while processing your password reset request. Try again soon!")


@users_router.post(path="/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(reset_password_schema: ResetPasswordSchema, header_token_dependency: headerTokenDependency):
    try:
        # token validation
        if not header_token_dependency.reset_password_token:
            raise ValueError("Reset password token is missing in the headers.")
        reset_password_data: dict = await cache_manager.get_reset_password_credentials(reset_password_token=header_token_dependency.reset_password_token)
        if not reset_password_data:
            raise ValueError("Your reset password token has expired. Please request a new one.")

        # data validation
        if not reset_password_schema.new_password:
            raise ValueError("New password is required.")
        if not reset_password_schema.code:
            raise ValueError("Code is required")

        # code assertion
        if reset_password_schema.code != reset_password_data.get("code"):
            raise ValueError("Your code is incorrect.")

        db_user: Optional[UserModel] = await UserModel.filter(email=reset_password_data.get("email")).first()
        if not db_user:
            raise ValueError("User not found with this email.")

        validate_password(password_string=reset_password_schema.new_password)

        hash_password = hashpw(password=reset_password_schema.new_password.encode(), salt=gensalt(rounds=8))
        if checkpw(hash_password, db_user.password.encode()):
            raise ValueError("Your new password must be different from the previous one.")

        db_user.password = hash_password.decode()
        await db_user.save()
        await cache_manager.remove_reset_password_credentials(reset_password_token=header_token_dependency.reset_password_token)

        return generate_token_response(user_id=db_user.id.hex)
    except ValueError as e:
        print(f"ValueError in reset_password: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in reset_password: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred in reset_password.")


@users_router.post(path="/refresh", status_code=status.HTTP_200_OK)
async def refresh(jwt_refresh_dependency: jwtRefreshDependency):
    try:
        subject = {"id": jwt_refresh_dependency.user_id}
        access_token = create_access_token(subject=subject)
        refresh_token = create_refresh_token(subject=subject)

        return {"access_token": access_token, "refresh_token": refresh_token}
    except Exception as e:
        print(f"Exception in refresh: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while refreshing the token.")


@users_router.post(path="/google_auth", status_code=status.HTTP_201_CREATED)
async def google_auth(header_token_dependency: headerTokenDependency):
    try:
        if not header_token_dependency.firebase_id_token:
            raise ValueError("Firebase ID token is missing in the headers.")

        firebase_user: UserRecord = await validate_firebase_token(header_token_dependency.firebase_id_token)

        print(f"firebase_user.display_name: {firebase_user.display_name}")

        db_user: Optional[UserModel] = await UserModel.get_or_none(email=firebase_user.email)
        if db_user:
            return generate_token_response(user_id=db_user.id.hex)

        username: str = generate_unique_username(base_name=firebase_user.display_name)
        password_string: str = generate_password_string()
        hash_password = hashpw(password=password_string.encode(), salt=gensalt(rounds=8)).decode()
        new_user: UserModel = await UserModel.create(username=username, email=firebase_user.email, password=hash_password)

        if firebase_user.photo_url:
            avatar_url: Optional[str] = await generate_avatar_url(image_url=firebase_user.photo_url, user_id=new_user.id)
            if avatar_url:
                new_user.avatar = avatar_url
                await new_user.save()

        await cache_manager.create_user_profile(new_user=new_user)

        await broadcast_stats_to_settings_task.kiq()
        await send_email_task.kiq(to_email=new_user.email, username=new_user.username, for_thanks_signing_up=True)

        return generate_token_response(user_id=new_user.id.hex)
    except ValueError as e:
        print(f"ValueError in social_auth: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in social_auth: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while getting user data.")


@users_router.get(path="/profile", status_code=status.HTTP_200_OK)
async def get_user(jwt_access_dependency: jwtAccessDependency):
    try:
        user_data: dict = await cache_manager.get_user_profile(user_id=jwt_access_dependency.user_id)
        if user_data:
            return user_data

        db_user: Optional[UserModel] = await UserModel.get_or_none(id=jwt_access_dependency.user_id)
        if not db_user:
            raise ValueError("User not found")

        await cache_manager.create_user_profile(new_user=db_user)

        return await generate_profile_response(db_user=db_user)
    except ValueError as e:
        print(f"ValueError in get_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in get_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while getting user data.")


@users_router.patch(path="/profile", status_code=status.HTTP_200_OK)
async def update_user(update_schema: UpdateSchema, jwt_access_dependency: jwtAccessDependency):
    try:
        await update_schema.model_async_validate()

        db_user: Optional[UserModel] = await UserModel.get_or_none(id=jwt_access_dependency.user_id)
        if not db_user:
            raise ValueError("User not found.")

        if update_schema.password:
            if checkpw(update_schema.password.encode(), db_user.password.encode()):
                update_schema.password = None
            else:
                hash_password: bytes = hashpw(password=update_schema.password.encode(), salt=gensalt(rounds=8))
                update_schema.password = hash_password.decode()

        if update_schema.is_admin is not None or update_schema.is_blocked is not None:
            if not db_user.is_admin:
                raise ValueError("🛑 Only admins can update these fields. Nice try though! 😜")

        if update_schema.avatar_file is not None:
            if update_schema.avatar_file.size == 0 or update_schema.avatar_file.filename == "":
                if db_user.avatar:
                    await remove_object_from_minio(object_name=db_user.avatar)
                    update_schema.avatar = None
            else:
                file_extension = get_file_extension(file=update_schema.avatar_file)
                if file_extension not in allowed_image_extension:
                    raise ValueError("🚫 Only PNG, JPG, and JPEG formats are allowed for avatars. No sneaky formats! ")
                object_name = f"users/{db_user.id.hex}/avatar.{file_extension}"
                avatar_bytes = await update_schema.avatar_file.read()
                avatar_object_name: str = await put_object_to_minio(object_name=object_name, data_stream=BytesIO(avatar_bytes), length=len(avatar_bytes))
                update_schema.avatar = avatar_object_name

        if update_schema.banner_file is not None:
            if update_schema.banner_file.size == 0 or update_schema.banner_file.filename == "":
                if db_user.banner:
                    await remove_object_from_minio(object_name=db_user.banner)
                    update_schema.banner = None
            else:
                file_extension = get_file_extension(file=update_schema.banner_file)
                if file_extension not in allowed_image_extension:
                    raise ValueError("Only png, jpg, jpeg image types allowed for banner image.")
                object_name = f"users/{db_user.id.hex}/banner.{file_extension}"
                banner_bytes = await update_schema.banner_file.read()
                banner_object_name: str = await put_object_to_minio(object_name=object_name, data_stream=BytesIO(banner_bytes), length=len(banner_bytes))
                update_schema.banner = banner_object_name

        update_ready_data: dict = update_schema.model_dump(exclude_defaults=True)

        print(f"📝 update_ready_data: {update_ready_data}")

        if len(update_ready_data.keys()) > 0:
            await db_user.update_from_dict(update_ready_data)
            await db_user.save()

        return await generate_profile_response(db_user=db_user)
    except ValueError as e:
        print(f"ValueError in update_user: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{e}")
    except Exception as e:
        print(f"Exception in update_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while updating the user.")


@users_router.delete(path="/profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(jwt_access_dependency: jwtAccessDependency):
    try:
        # delete all media files
        await wipe_objects_from_minio(user_id=jwt_access_dependency.user_id)

        # delete from database
        db_user: Optional[UserModel] = await UserModel.get_or_none(id=jwt_access_dependency.user_id)
        if db_user:
            # delete from redis
            await cache_manager.delete_user_profile(user_id=jwt_access_dependency.user_id, username=db_user.username, email=db_user.email)
            await db_user.delete()

        return {}
    except Exception as e:
        print(f"Exception in delete_user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while deleting the user.")


@users_router.get(path="/all", status_code=status.HTTP_200_OK)
async def get_users():
    try:
        my_logger.critical("request come to get_users route.")
        users_model = await UserModel.all()
        print(f"users_model: {users_model}")

        if users_model:
            print(f"📝 users_model length: {len(users_model)}")
            return [(await UserProfilePydantic.from_tortoise_orm(user_model)).model_dump() for user_model in users_model]

        return []
    except Exception as e:
        print(f"Exception in get_users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while getting the users.")


@users_router.delete(path="/profile-delete-by-id", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_by_id(user_id: str):
    try:
        # delete all media files
        await wipe_objects_from_minio(user_id=user_id)

        # delete from database
        db_user: Optional[UserModel] = await UserModel.get_or_none(id=user_id)
        if db_user:
            # delete from redis
            await cache_manager.delete_user_profile(user_id=user_id, username=db_user.username, email=db_user.email)
            await db_user.delete()

        return {}
    except Exception as e:
        print(f"Exception in delete_user_by_id: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal server error occurred while deleting the user by id.")


@users_router.get(path="/delete_all_users", status_code=status.HTTP_204_NO_CONTENT)
async def delete_users():
    await UserModel.all().delete()
    return {"message": "All users deleted. 🗑️"}


def generate_token_response(user_id: str):
    subject = {"id": user_id}
    return {
        "access_token": create_access_token(subject=subject),
        "refresh_token": create_refresh_token(subject=subject),
    }


async def generate_profile_response(db_user: UserModel):
    user_pydantic_model: PydanticModel = await UserProfilePydantic.from_tortoise_orm(obj=db_user)

    user_dict = user_pydantic_model.model_dump(exclude_none=False)
    followers_count = await db_user.followers.all().count()
    followings_count = await db_user.followings.all().count()
    # print(f"🚧 user_dict: {user_dict}")

    return {**user_dict, "followers_count": followers_count, "followings_count": followings_count}
