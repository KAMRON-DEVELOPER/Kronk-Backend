from functools import lru_cache
from pathlib import Path
from typing import Optional

from firebase_admin import credentials
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BASE_DIR: Optional[str] = str(Path(__file__).parent.parent.parent)
    DATABASE_URL: Optional[str]  =None
    REDIS_URL: Optional[str] = None

    # MINIO
    MINIO_ROOT_USER: Optional[str] = None
    MINIO_ROOT_PASSWORD: Optional[str] = None
    MINIO_ENDPOINT: Optional[str] = None
    MINIO_BUCKET_NAME: Optional[str] = None

    # FASTAPI JWT
    SECRET_KEY: Optional[str] = None
    ALGORITHM: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_TIME: Optional[str] = None
    REFRESH_TOKEN_EXPIRE_TIME: Optional[str] = None

    # EMAIL
    EMAIL_SERVICE_API_KEY: Optional[str] = None

    # FIREBASE
    FIREBASE_TYPE: Optional[str] = None
    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_PRIVATE_KEY_ID: Optional[str] = None
    FIREBASE_PRIVATE_KEY: Optional[str] = None
    FIREBASE_CLIENT_EMAIL: Optional[str] = None
    FIREBASE_CLIENT_ID: Optional[str] = None
    FIREBASE_AUTH_URI: Optional[str] = None
    FIREBASE_TOKEN_URI: Optional[str] = None
    FIREBASE_AUTH_PROVIDER_X509_CERT_URI: Optional[str] = None
    FIREBASE_CLIENT_CERT_URL: Optional[str] = None

    # AZURE TRANSLATOR
    AZURE_TRANSLATOR_KEY: Optional[str] = None
    AZURE_TRANSLATOR_REGION: Optional[str] = None
    AZURE_TRANSLATOR_ENDPOINT: Optional[str] = None

    def get_tortoise_orm(self) -> dict:
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL is not set!")
        return {
            "connections": {"default": self.DATABASE_URL},
            "apps": {
                "users_app": {"models": ["app.users_app.models"], "default_connection": "default"},
                "community_app": {"models": ["app.community_app.models"], "default_connection": "default"},
                "education_app": {"models": ["app.education_app.models"], "default_connection": "default"},
            },
        }

    def get_firebase_credentials(self):
        if not self.FIREBASE_TYPE or not self.FIREBASE_PRIVATE_KEY:
            raise ValueError("Firebase credentials are not properly set!")
        return credentials.Certificate(
            {
                "type": self.FIREBASE_TYPE,
                "project_id": self.FIREBASE_PROJECT_ID,
                "private_key_id": self.FIREBASE_PRIVATE_KEY_ID,
                "private_key": self.FIREBASE_PRIVATE_KEY,  # .replace("\\n", "\n"),  # Handle multiline private key
                "client_email": self.FIREBASE_CLIENT_EMAIL,
                "client_id": self.FIREBASE_CLIENT_ID,
                "auth_uri": self.FIREBASE_AUTH_URI,
                "token_uri": self.FIREBASE_TOKEN_URI,
                "auth_provider_x509_cert_url": self.FIREBASE_AUTH_PROVIDER_X509_CERT_URI,
                "client_x509_cert_url": self.FIREBASE_CLIENT_CERT_URL,
            }
        )

    model_config = SettingsConfigDict(env_file=[".env"], env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings():
    return Settings()
