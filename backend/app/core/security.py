import asyncio
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import jwt
from anyio import to_thread
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.config import settings


password_hash = PasswordHash.recommended()
PASSWORD_HASH_MAX_CONCURRENCY = settings.PASSWORD_HASH_MAX_CONCURRENCY

# 这个 Semaphore 只约束当前 Python 进程。部署多个 Uvicorn Worker 时，
# 整台机器的最大并发哈希数约为 Worker 数量乘以 5。
_password_hash_semaphore = asyncio.Semaphore(PASSWORD_HASH_MAX_CONCURRENCY)
_dummy_password_hash: str | None = None
_dummy_password_hash_lock = asyncio.Lock()
_R = TypeVar("_R")


class PasswordHashCapacityError(RuntimeError):
    """Argon2 工作槽已满，请求在限定时间内无法开始。"""


async def _run_password_operation(
    operation: Callable[..., _R],
    *args: object,
) -> _R:
    """只对等待工作槽设置超时；Argon2 开始后必须等它结束再释放工作槽。"""
    try:
        await asyncio.wait_for(
            _password_hash_semaphore.acquire(),
            timeout=settings.PASSWORD_HASH_WAIT_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise PasswordHashCapacityError(
            "Password hashing capacity is temporarily exhausted"
        ) from exc

    try:
        return await to_thread.run_sync(operation, *args)
    finally:
        _password_hash_semaphore.release()


async def hash_password(plain_password: str) -> str:
    """在线程池中执行 Argon2，并限制当前进程最多并发 5 个哈希。"""
    return await _run_password_operation(password_hash.hash, plain_password)


async def verify_password(plain_password: str, stored_password_hash: str) -> bool:
    """在线程池中验证密码，并限制当前进程最多并发 5 个哈希。"""
    return await _run_password_operation(
        password_hash.verify,
        plain_password,
        stored_password_hash,
    )


async def initialize_password_security() -> None:
    """应用启动时在线程池生成固定假哈希，供不存在的用户名使用。"""
    global _dummy_password_hash

    if _dummy_password_hash is not None:
        return

    async with _dummy_password_hash_lock:
        if _dummy_password_hash is None:
            _dummy_password_hash = await hash_password(
                secrets.token_urlsafe(32)
            )


def get_dummy_password_hash() -> str:
    """取得启动时生成的假哈希；未初始化表示应用生命周期配置错误。"""
    if _dummy_password_hash is None:
        raise RuntimeError("Password security has not been initialized")
    return _dummy_password_hash


def create_access_token(user_id: str) -> str:
    """为已经通过登录校验的用户签发短期 Access Token。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> str:
    """验证 Access Token，并返回其中可信的 user_id。"""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["sub", "iat", "exp", "jti", "type"]},
    )

    if payload.get("type") != "access":
        raise InvalidTokenError("Token type is not access")

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidTokenError("Token subject is invalid")

    return user_id
