from typing import Annotated, Optional
from fastapi import Depends, Request, Security, HTTPException, WebSocketException
from app.utility.jwt_utils import verify_jwt_token, JWTCredential
from fastapi import WebSocket, status


class HeaderTokensCredential:
    def __init__(self, verify_token: Optional[str], reset_password_token: Optional[str], firebase_id_token: Optional[str]):
        self.verify_token: Optional[str] = verify_token
        self.reset_password_token: Optional[str] = reset_password_token
        self.firebase_id_token: Optional[str] = firebase_id_token


class WebsocketCredential:
    def __init__(self, user_id: str, websocket: WebSocket):
        self.user_id = user_id
        self.websocket = websocket


def header_token_dependency(request: Request):
    verify_token: Optional[str] = request.headers.get("verify-token")
    reset_password_token: Optional[str] = request.headers.get("reset-password-token")
    firebase_id_token: Optional[str] = request.headers.get("firebase-id-token")
    return HeaderTokensCredential(verify_token=verify_token, reset_password_token=reset_password_token, firebase_id_token=firebase_id_token)


def get_current_user(token: str = Security(lambda token: token)) -> JWTCredential:
    """FastAPI Security Dependency to verify JWT token."""
    jwt_credential = verify_jwt_token(token)
    if jwt_credential is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return jwt_credential


async def websocket_resolver(websocket: WebSocket) -> Optional[WebsocketCredential]:
    """Extract and verify JWT from WebSocket headers."""
    token = websocket.headers.get("Authorization")
    if not token or not token.startswith("Bearer "):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    jwt_credential = verify_jwt_token(token=token.split(" ")[1])
    return WebsocketCredential(user_id=jwt_credential.user_id, websocket=websocket)


headerTokenDependency = Annotated[HeaderTokensCredential, Depends(dependency=header_token_dependency)]
jwtAccessDependency = Annotated[JWTCredential, Security(dependency=get_current_user)]
jwtRefreshDependency = Annotated[JWTCredential, Security(dependency=get_current_user)]
websocketDependency = Annotated[WebsocketCredential, Depends(dependency=websocket_resolver)]
