from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError

from app.core.security import decode_access_token
from app.dependencies.database import get_db
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import AuthenticatedUser


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db=Depends(get_db),
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

    user = await AuthRepository(db).find_by_user_id(user_id)
    if user is None:
        raise credentials_exception

    if user.get("disabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已经被禁用",
        )

    return AuthenticatedUser(
        user_id=user["user_id"],
        username=user["username"],
    )


async def get_current_user_id(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> str:
    return current_user.user_id
