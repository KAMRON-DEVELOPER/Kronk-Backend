from typing import Annotated, Optional

from app.utility.jwt_utils import JWTCredential, verify_jwt_token
from fastapi import Depends, Header, HTTPException, WebSocket, WebSocketException, status


class HeaderTokensCredential:
    def __init__(self, verify_token: Optional[str], reset_password_token: Optional[str], firebase_id_token: Optional[str]):
        self.verify_token: Optional[str] = verify_token
        self.reset_password_token: Optional[str] = reset_password_token
        self.firebase_id_token: Optional[str] = firebase_id_token


class WebsocketCredential:
    def __init__(self, user_id: str, websocket: WebSocket):
        self.user_id = user_id
        self.websocket = websocket


def token_resolver(
        verify_token: Optional[str] = Header(default=None),
        reset_password_token: Optional[str] = Header(default=None),
        firebase_id_token: Optional[str] = Header(default=None),
):
    # verify_token: Optional[str] = request.headers.get("verify-token")
    # reset_password_token: Optional[str] = request.headers.get("reset-password-token")
    # firebase_id_token: Optional[str] = request.headers.get("firebase-id-token")
    return HeaderTokensCredential(verify_token=verify_token, reset_password_token=reset_password_token, firebase_id_token=firebase_id_token)


def jwt_resolver(authorization: str = Header(default=None)) -> JWTCredential:
    """FastAPI Security Dependency to verify JWT token."""
    print(f"authorization: {authorization}")

    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token.")

    token = authorization.split(" ")[1]
    jwt_credential = verify_jwt_token(token)

    if jwt_credential is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

    return jwt_credential


async def websocket_resolver(websocket: WebSocket) -> WebsocketCredential:
    """Extract and verify JWT from WebSocket headers."""
    token = websocket.headers.get("Authorization")
    if not token or not token.startswith("Bearer "):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    jwt_credential = verify_jwt_token(token=token.split(" ")[1])
    return WebsocketCredential(user_id=jwt_credential.user_id, websocket=websocket)


headerTokenDependency = Annotated[HeaderTokensCredential, Depends(dependency=token_resolver)]
jwtAccessDependency = Annotated[JWTCredential, Depends(dependency=jwt_resolver)]
jwtRefreshDependency = Annotated[JWTCredential, Depends(dependency=jwt_resolver)]
websocketDependency = Annotated[WebsocketCredential, Depends(dependency=websocket_resolver)]
