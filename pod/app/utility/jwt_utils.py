from datetime import UTC, datetime, timedelta

from app.settings.my_config import get_settings
from authlib.jose import JWTClaims, jwt
from app.utility.my_logger import my_logger

settings = get_settings()


def create_jwt_token(subject: dict, for_refresh: bool = False) -> str:
    """Generate a JWT token using Authlib."""
    header = {"alg": settings.ALGORITHM}
    access_exp = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_TIME)
    refresh_exp = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_TIME)
    exp = refresh_exp if for_refresh else access_exp
    payload = {"exp": exp, "sub": subject}
    return jwt.encode(header=header, payload=payload, key=settings.SECRET_KEY.encode("utf-8")).decode("utf-8")


class JWTCredential:
    def __init__(self, user_id: str):
        self.user_id = user_id


def verify_jwt_token(token: str) -> JWTCredential:
    """Verify and decode a JWT token."""
    try:
        decoded: JWTClaims = jwt.decode(s=token, key=settings.SECRET_KEY.encode("utf-8"))
        if datetime.now(UTC).timestamp() > decoded["exp"]:
            raise ValueError("Token is expired.")
        # my_logger.debug(f"decoded: {decoded}; decoded.keys(): {decoded.keys()}; decoded.values(): {decoded.values()}")
        try:
            return JWTCredential(user_id=decoded["sub"]["id"])
        except KeyError as e:
            my_logger.warning(f"KeyError in verify_jwt_token: {e}")
            raise ValueError(f"KeyError in verify_jwt_token: {e}")
    except Exception as e:
        raise ValueError(f"Exception in verify_jwt_token: {e}")
