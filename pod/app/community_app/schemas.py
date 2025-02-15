import os
from datetime import datetime
from typing import Optional

import aiofiles
from dateutil.parser import parse
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic_async_validation import AsyncValidationModelMixin, async_field_validator

from app.settings.my_config import get_settings
from app.settings.my_minio import put_object_to_minio
from app.utility.decorator import create_as_form
from app.utility.validators import allowed_image_extension, allowed_video_extension, get_file_extension, get_video_duration


class PostCreateScheme(AsyncValidationModelMixin, BaseModel):
    body: Optional[str]
    scheduled_time: Optional[datetime]
    images: Optional[list[str]]
    video: Optional[str]
    image_files: Optional[list[UploadFile]]
    video_file: Optional[UploadFile]

    class Config:
        from_attributes = True

    @async_field_validator("body")
    async def validate_body(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("body is required.")
        if len(value) > 200:
            raise ValueError("body is exceeded max 200 character limit.")

    @async_field_validator("scheduled_time")
    async def validate_scheduled(self, value: str) -> None:
        try:
            parse(timestr=value)
        except Exception as e:
            raise ValueError(f"schedule time is invalid. {e}")

    @async_field_validator("image_files")
    async def validate_image(self, value: Optional[list[UploadFile]]) -> None:
        if value:
            if len(value) > 4:
                raise ValueError("each post allowed images limit is 4")
            for _value in value:
                if get_file_extension(file=_value) not in allowed_image_extension:
                    raise ValueError("not supported image format provided.")
                object_name = await put_object_to_minio(object_name=f"community_app/posts/images/{_value.filename}", data=await _value.read())
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
            object_name = await put_object_to_minio(object_name=value.filename, data=video_bytes)
            self.video = object_name

        os.remove(path=temp_file_path)

    @classmethod
    def as_form(cls):
        return create_as_form(cls)

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
            object_name = await put_object_to_minio(object_name=f"community_app/posts/images/{_value.filename}", data=await _value.read(), for_update=True)
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
            object_name = await put_object_to_minio(object_name=value.filename, data=video_bytes, for_update=True)
            self.video = object_name

        os.remove(path=temp_file_path)

    @classmethod
    def as_form(cls):
        return create_as_form(cls)

    def __str__(self):
        return "<🚧 PostUpdateSchema>"
