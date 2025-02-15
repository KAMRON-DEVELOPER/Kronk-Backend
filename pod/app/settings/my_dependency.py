from datetime import timedelta
from typing import Annotated, Optional

from fastapi import Depends, Request, Security
from fastapi_jwt import JwtAccessBearer, JwtAuthorizationCredentials, JwtRefreshBearer

from app.settings.my_config import get_settings


class HeaderTokensCredential:
    def __init__(self, verify_token: Optional[str], reset_password_token: Optional[str], firebase_id_token: Optional[str]):
        self.verify_token: Optional[str] = verify_token
        self.reset_password_token: Optional[str] = reset_password_token
        self.firebase_id_token: Optional[str] = firebase_id_token


def header_token_dependency(request: Request):
    verify_token: Optional[str] = request.headers.get("verify-token")
    reset_password_token: Optional[str] = request.headers.get("reset-password-token")
    firebase_id_token: Optional[str] = request.headers.get("firebase-id-token")
    return HeaderTokensCredential(verify_token=verify_token, reset_password_token=reset_password_token, firebase_id_token=firebase_id_token)


access_security = JwtAccessBearer(
    secret_key=get_settings().SECRET_KEY.__str__(),
    auto_error=True,
    algorithm=get_settings().ALGORITHM,
    access_expires_delta=timedelta(minutes=30),
    refresh_expires_delta=timedelta(days=1),
)
refresh_security = JwtRefreshBearer.from_other(access_security)

jwtAccessDependency = Annotated[JwtAuthorizationCredentials, Security(dependency=access_security)]
jwtRefreshDependency = Annotated[JwtAuthorizationCredentials, Security(dependency=refresh_security)]
headerTokenDependency = Annotated[HeaderTokensCredential, Depends(dependency=header_token_dependency)]
