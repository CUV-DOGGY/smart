import logging
import math
from typing import Annotated, Never

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis

from app.config import settings
from app.core.client_ip import get_client_ip
from app.core.security import PasswordHashCapacityError
from app.dependencies.cache import get_redis
from app.dependencies.auth import get_current_user
from app.dependencies.services import get_auth_service
from app.schemas.auth import (
    AuthenticatedUser,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.services.auth_service import (
    AuthenticationError,
    AuthService,
    UsernameAlreadyExistsError,
)
from app.services.auth_rate_limiter import (
    AuthRateLimiter,
    RateLimitBackendError,
    RateLimitExceeded,
)


router = APIRouter(prefix="/auth", tags=["用户认证"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=AuthenticatedUser)
async def me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    return current_user


def get_auth_rate_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
) -> AuthRateLimiter:
    return AuthRateLimiter(redis)


def raise_rate_limit_error(exc: RuntimeError) -> Never:
    if isinstance(exc, RateLimitExceeded):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务暂时不可用",
    ) from exc


def raise_password_capacity_error(exc: PasswordHashCapacityError) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="认证服务繁忙，请稍后重试",
        headers={
            "Retry-After": str(
                max(1, math.ceil(settings.PASSWORD_HASH_WAIT_TIMEOUT_SECONDS))
            )
        },
    ) from exc


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    raw_request: Request,
    request: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
    rate_limiter: Annotated[AuthRateLimiter, Depends(get_auth_rate_limiter)],
):
    try:
        await rate_limiter.check_registration(
            client_ip=get_client_ip(raw_request, settings.TRUSTED_PROXY_CIDRS),
            username=request.username,
        )
        return await service.register(request)
    except (RateLimitExceeded, RateLimitBackendError) as exc:
        raise_rate_limit_error(exc)
    except PasswordHashCapacityError as exc:
        raise_password_capacity_error(exc)
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    service: Annotated[AuthService, Depends(get_auth_service)],
    rate_limiter: Annotated[AuthRateLimiter, Depends(get_auth_rate_limiter)],
):
    try:
        await rate_limiter.check_login(
            client_ip=get_client_ip(request, settings.TRUSTED_PROXY_CIDRS),
            username=form_data.username,
        )
        response = await service.login(
            username=form_data.username,
            password=form_data.password,
        )
        try:
            await rate_limiter.reset_username_after_success(form_data.username)
        except RateLimitBackendError:
            # 本次请求已在 Redis 正常时通过限流和密码校验。
            # 重置失败不应丢弃已签发的令牌；后续请求仍会 fail-closed。
            logger.warning("登录成功后重置用户名限流计数失败")
        return response
    except (RateLimitExceeded, RateLimitBackendError) as exc:
        raise_rate_limit_error(exc)
    except PasswordHashCapacityError as exc:
        raise_password_capacity_error(exc)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
