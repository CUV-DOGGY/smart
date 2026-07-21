import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.config import settings


password_hash = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """将明文密码转换成不可逆的密码哈希。"""
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, stored_password_hash: str) -> bool:
    """验证明文密码是否与数据库中的密码哈希匹配。"""
    return password_hash.verify(plain_password, stored_password_hash)


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
