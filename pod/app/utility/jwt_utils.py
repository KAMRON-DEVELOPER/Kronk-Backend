from datetime import timedelta
from datetime import datetime, UTC
from typing import Optional
from authlib.jose import jwt, JoseError
from app.settings.my_config import get_settings

'''Load settings'''
settings = get_settings()

'''JWT Configuration'''

SECRET_KEY = settings.SECRET_KEY.encode("utf-8")  # Authlib requires bytes
ALGORITHM = settings.ALGORITHM  # Example: "HS256"
ACCESS_TOKEN_EXPIRE_TIME = settings.ACCESS_TOKEN_EXPIRE_TIME


def create_jwt_token(subject: dict) -> str:
    """Generate a JWT token using Authlib."""
    header = {"alg": ALGORITHM}
    payload = {"exp": datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_TIME), "sub": subject}
    return jwt.encode(header=header, payload=payload, key=SECRET_KEY).decode("utf-8")


class JWTCredential:
    def __init__(self, user_id: str):
        self.user_id = user_id


def verify_jwt_token(token: str) -> Optional[JWTCredential]:
    """Verify and decode a JWT token."""
    try:
        decoded = jwt.decode(s=token, key=SECRET_KEY)
        if datetime.now(UTC).timestamp() > decoded["exp"]:
            return None
        return JWTCredential(user_id=decoded["sub"]["id"])
    except JoseError:
        return None


def create_access_token(subject: dict) -> str:
    """Generate an access token."""
    return create_jwt_token(subject=subject)


def create_refresh_token(subject: dict) -> str:
    """Generate a refresh token."""
    return create_jwt_token(subject=subject)
