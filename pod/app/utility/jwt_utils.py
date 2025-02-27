from datetime import UTC, datetime, timedelta
from typing import Optional

from app.settings.my_config import get_settings
from authlib.jose import JoseError, JWTClaims, jwt

"""Load settings"""
settings = get_settings()

"""JWT Configuration"""

SECRET_KEY = settings.SECRET_KEY.encode("utf-8")  # Authlib requires bytes
ALGORITHM = settings.ALGORITHM  # Example: "HS256"


def create_jwt_token(subject: dict, for_refresh: bool = False) -> str:
    """Generate a JWT token using Authlib."""
    header = {"alg": ALGORITHM}
    access_exp = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_TIME)
    refresh_exp = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_TIME)
    exp = refresh_exp if for_refresh else access_exp
    payload = {"exp": exp, "sub": subject}
    return jwt.encode(header=header, payload=payload, key=SECRET_KEY).decode("utf-8")


class JWTCredential:
    def __init__(self, user_id: str):
        self.user_id = user_id


def verify_jwt_token(token: str) -> Optional[JWTCredential]:
    """Verify and decode a JWT token."""
    try:
        decoded: JWTClaims = jwt.decode(s=token, key=SECRET_KEY)
        if datetime.now(UTC).timestamp() > decoded["exp"]:
            return None
        return JWTCredential(user_id=decoded["sub"]["id"])
    except JoseError:
        return None
