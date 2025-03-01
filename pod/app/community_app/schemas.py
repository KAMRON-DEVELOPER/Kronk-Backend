import os
from dataclasses import dataclass
from io import BytesIO
from typing import Annotated, Callable, Optional
from uuid import UUID

import aiofiles
from app.settings.my_config import get_settings
from app.settings.my_minio import put_object_to_minio
from app.utility.decorator import as_form
from app.utility.my_logger import my_logger
from app.utility.validators import allowed_image_extension, allowed_video_extension, get_file_extension, get_video_duration
from fastapi import File, Form, UploadFile
from pydantic import BaseModel, Field
from pydantic_async_validation import AsyncValidationModelMixin, async_field_validator


class FollowScheme(AsyncValidationModelMixin, BaseModel):
    follower_id: UUID = Field()

    class Config:
        from_attributes = True

    @async_field_validator("follower_ids")
    async def validate_body(self, value) -> None:
        my_logger.debug(f"value: {value}, type: {type(value)}")


@dataclass
class PostCreate:
    body: Optional[str] = Form(...)
    images: Optional[list[str]] = Form(...)
    video: Optional[str] = Form(...)
    scheduled_time: Optional[str] = Form(...)
    image_files: Optional[list[UploadFile]] = File(...)
    video_file: Optional[UploadFile] = File(...)


class PostCreateInit(BaseModel):
    def __init__(
        self,
        body: Annotated[Optional[str], Form()],
        images: Annotated[Optional[str], Form()],
        video: Annotated[Optional[str], Form()],
        scheduled_time: Annotated[Optional[str], Form()],
        image_files: Annotated[Optional[list[UploadFile]], File()],
        video_file: Annotated[Optional[UploadFile], File()],
    ):
        super().__init__(body=body, images=images, video=video, scheduled_time=scheduled_time, image_files=image_files, video_file=video_file)

    body: Annotated[Optional[str], Form()]
    images: Annotated[Optional[str], Form()]
    video: Annotated[Optional[str], Form()]
    scheduled_time: Annotated[Optional[str], Form()]
    image_files: Annotated[Optional[list[UploadFile]], File()]
    video_file: Annotated[Optional[UploadFile], File()]


@as_form
class PostCreateScheme(BaseModel):
    body: Optional[str] = None
    images: Optional[list[str]] = None
    video: Optional[str] = None
    scheduled_time: Optional[str] = None
    image_files: Optional[list[UploadFile]] = None
    video_file: Optional[UploadFile] = None

    @classmethod
    def as_form(cls) -> Callable[..., "PostCreateScheme"]:
        pass  # This is just to help IDEs recognize `as_form` and making IDEs happy.

    class Config:
        from_attributes = True

    # @async_field_validator("body")
    # async def validate_body(self, value: Optional[str]) -> None:
    #     if value is None:
    #         raise ValueError("body is required.")
    #     if len(value) > 200:
    #         raise ValueError("body is exceeded max 200 character limit.")
    #
    # @async_field_validator("scheduled_time")
    # async def validate_scheduled(self, value: Optional[datetime]) -> None:
    #     try:
    #         if value is not None:
    #             pass
    #             # parse(timestr=value)
    #     except Exception as e:
    #         raise ValueError(f"schedule time is invalid. {e}")
    #
    # @async_field_validator("image_files")
    # async def validate_image(self, value: Optional[list[UploadFile]]) -> None:
    #     if value:
    #         if len(value) > 4:
    #             raise ValueError("each post allowed images limit is 4")
    #         for _value in value:
    #             if get_file_extension(file=_value) not in allowed_image_extension:
    #                 raise ValueError("not supported image format provided.")
    #             _value_bytes = await _value.read()
    #             object_name = await put_object_to_minio(
    #                 object_name=f"community_app/posts/images/{_value.filename}",
    #                 data_stream=BytesIO(_value_bytes),
    #                 length=len(_value_bytes),
    #             )
    #             self.images.append(object_name)
    #
    # @async_field_validator("video_file")
    # async def validate_video(self, value: Optional[UploadFile]) -> None:
    #     if value:
    #         if get_file_extension(file=value) not in allowed_video_extension:
    #             raise ValueError("not supported video format provided.")
    #
    #     temp_file_path = f"{get_settings().BASE_DIR}/temp_files/videos/{value.filename}"
    #
    #     async with aiofiles.open(file=temp_file_path, mode="wb") as temp_file:
    #         contents = await value.read()
    #         await temp_file.write(contents)
    #         await temp_file.flush()  # Ensure all data is written to disk
    #
    #         file_path = temp_file.name  # Get actual file path
    #         duration = await get_video_duration(file_path=file_path)
    #         if duration > 140:
    #             raise ValueError("video exceeds the max allowed duration of 140 seconds.")
    #
    #     async with aiofiles.open(file=temp_file_path, mode="rb") as temp_file:
    #         video_bytes = await temp_file.read()
    #         object_name = await put_object_to_minio(object_name=value.filename, data_stream=BytesIO(video_bytes), length=len(video_bytes))
    #         self.video = object_name
    #
    #     os.remove(path=temp_file_path)

    def __str__(self) -> str:
        return "<🚧 CreatePostScheme>"


class PostUpdateSchema(AsyncValidationModelMixin, BaseModel):
    body: Optional[str] = None
    images: Optional[list[str]]
    video: Optional[str]
    image_files: Optional[list[UploadFile]] = None
    video_file: Optional[UploadFile] = None

    @async_field_validator("body")
    async def validate_body(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("body is required.")
        if len(value) > 200:
            raise ValueError("body is exceeded max 200 character limit.")

    @async_field_validator("image_files")
    async def validate_image(self, value: list[UploadFile]) -> None:
        if len(value) > 4:
            raise ValueError("each post allowed images limit is 4")
        for _value in value:
            if get_file_extension(file=_value) not in allowed_image_extension:
                raise ValueError("not supported image format provided.")
            _value_bytes = await _value.read()
            object_name = await put_object_to_minio(
                object_name=f"community_app/posts/images/{_value.filename}",
                data_stream=BytesIO(_value_bytes),
                length=len(_value_bytes),
                for_update=True,
            )
            self.images.append(object_name)

    @async_field_validator("video_file")
    async def validate_video(self, value: UploadFile) -> None:
        if get_file_extension(file=value) not in allowed_video_extension:
            raise ValueError("not supported video format provided.")

        temp_file_path = f"{get_settings().BASE_DIR}/temp_files/videos/{value.filename}"

        async with aiofiles.open(file=temp_file_path, mode="wb") as temp_file:
            contents = await value.read()
            await temp_file.write(contents)
            await temp_file.flush()  # Ensure all data is written to disk

            file_path = temp_file.name  # Get actual file path
            duration = await get_video_duration(file_path=file_path)
            if duration > 140:
                raise ValueError("video exceeds the max allowed duration of 140 seconds.")

        async with aiofiles.open(file=temp_file_path, mode="rb") as temp_file:
            video_bytes = await temp_file.read()
            object_name = await put_object_to_minio(object_name=value.filename, data_stream=BytesIO(video_bytes), length=len(video_bytes), for_update=True)
            self.video = object_name

        os.remove(path=temp_file_path)

    def __str__(self):
        return "<🚧 PostUpdateSchema>"
