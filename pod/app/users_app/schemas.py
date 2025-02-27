import re
from datetime import datetime, timedelta
from typing import Optional

from app.utility.decorator import create_as_form
from app.utility.validators import validate_email, validate_length, validate_password, validate_username, violent_words_regex
from dateutil.parser import parse
from fastapi import UploadFile
from pydantic import BaseModel
from pydantic_async_validation import AsyncValidationModelMixin, async_field_validator


class RegisterSchema(AsyncValidationModelMixin, BaseModel):
    username: Optional[str]
    email: Optional[str]
    password: Optional[str]

    @async_field_validator("username")
    async def validate_code(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Username is required.")
        validate_username(username=value)

    @async_field_validator("email")
    async def validate_email(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Email is required.")
        validate_email(email=value)

    @async_field_validator("password")
    async def validate_password(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Password is required.")
        validate_password(password_string=value)

    def __str__(self) -> str:
        return "<🚧 RegisterSchema"


class VerifySchema(AsyncValidationModelMixin, BaseModel):
    code: Optional[str]

    @async_field_validator("code")
    async def validate_code(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Code is required.")
        if not value.isdigit():
            raise ValueError("Code must contain only digits.")
        if len(value) != 4:
            raise ValueError("Code must be 4 digit long.")

    def __str__(self) -> str:
        return "<🚧 VerifySchema"


class RequestResetPasswordSchema(AsyncValidationModelMixin, BaseModel):
    email: Optional[str]

    @async_field_validator("email")
    async def validate_email(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Email is required.")
        validate_email(email=value)

    def __str__(self) -> str:
        return "<🚧 RequestResetPasswordSchema"


class ResetPasswordSchema(AsyncValidationModelMixin, BaseModel):
    code: Optional[str]
    new_password: Optional[str]

    @async_field_validator("code")
    async def validate_code(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Code is required.")
        if not value.isdigit():
            raise ValueError("Code must contain only digits.")
        if len(value) != 4:
            raise ValueError("Code must be 4 digit long.")

    @async_field_validator("new_password")
    async def validate_new_password(self, value: Optional[str]):
        if value is None:
            raise ValueError("New password is required.")
        validate_password(password_string=value)

    def __str__(self) -> str:
        return "<🚧 ResetPasswordSchema"


class LoginSchema(AsyncValidationModelMixin, BaseModel):
    username: Optional[str]
    password: Optional[str]

    @async_field_validator("username")
    async def validate_code(self, value: Optional[str]) -> None:
        if value is None:
            raise ValueError("Username is required.")
        validate_username(username=value)

    @async_field_validator("password")
    async def validate_password(self, value: Optional[str]):
        if value is None:
            raise ValueError("Password is required.")
        validate_password(password_string=value)

    def __str__(self) -> str:
        return "<🚧 LoginModel"


class UpdateSchema(AsyncValidationModelMixin, BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    avatar: Optional[str] = None
    banner: Optional[str] = None
    avatar_file: Optional[UploadFile] = None
    banner_file: Optional[UploadFile] = None
    birthdate: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    is_admin: Optional[bool] = None
    is_blocked: Optional[bool] = None

    @async_field_validator("username")
    async def validate_code(self, value: Optional[str]) -> None:
        if value is not None:
            if not value:
                raise ValueError("Username cannot be empty.")
            validate_username(username=value)

    @async_field_validator("email")
    async def validate_email(self, value: Optional[str]) -> None:
        if value is not None:
            if not value:
                raise ValueError("Email cannot be empty.")
            validate_email(email=value)

    @async_field_validator("password")
    async def validate_password(self, value: Optional[str]):
        if value is not None:
            if not value:
                raise ValueError("Password cannot be empty.")
            validate_password(password_string=value)

    @async_field_validator("first_name")
    async def validate_first_name(self, value: Optional[str]) -> None:
        if value is not None:
            validate_length(field=value, min_len=3, max_len=20, field_name="First name")
            if not value.isalnum() and value != "":
                raise ValueError("First name must contain only alphanumeric characters.")

    @async_field_validator("last_name")
    async def validate_last_name(self, value: Optional[str]) -> None:
        if value is not None:
            validate_length(field=value, min_len=3, max_len=20, field_name="First name")
            if not value.isalnum() and value != "":
                raise ValueError("Last name must contain only alphanumeric characters.")

    @async_field_validator("birthdate")
    async def validate_birthdate(self, value: Optional[str]) -> None:
        if value is not None:
            try:
                birthdate = parse(timestr=value)
            except Exception as _:
                raise ValueError("Invalid birthdate format.")
            min_age_date = datetime.now() - timedelta(days=6 * 365)
            max_age_date = datetime.now() - timedelta(days=100 * 365)
            if not (max_age_date <= birthdate <= min_age_date):
                raise ValueError("Birthdate must be between 6 and 100 years ago.")

    @async_field_validator("bio")
    async def validate_bio(self, value: Optional[str]) -> None:
        if value is not None:
            validate_length(field=value, min_len=0, max_len=200, field_name="bio")
            if re.search(violent_words_regex, value, re.IGNORECASE):
                raise ValueError("Bio contains sensitive or inappropriate content.")

    @classmethod
    def as_form(cls):
        return create_as_form(cls)

    def __str__(self):
        return "<🚧 UpdateModel"
