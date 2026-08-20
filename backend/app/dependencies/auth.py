from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError

from app.core.security import decode_access_token
from app.dependencies.services import get_auth_service
from app.schemas.auth import AuthenticatedUser
from app.services.auth_service import AuthService


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态无效或已经过期",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_exception

    user = await service.authenticated_user(user_id)
    if user is None:
        raise credentials_exception
    return user


async def get_current_user_id(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> str:
    return current_user.user_id
