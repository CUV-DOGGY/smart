import hashlib
import hmac
import ipaddress

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.core.auth_policy import normalize_username


RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RateLimitExceeded(RuntimeError):
    """认证请求超过频率限制。"""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RateLimitBackendError(RuntimeError):
    """Redis 不可用，无法安全执行认证请求。"""


def normalize_client_ip(client_ip: str) -> str:
    try:
        return ipaddress.ip_address(client_ip).compressed
    except ValueError:
        return client_ip.strip()[:128] or "unknown"


def digest_key_part(value: str, secret: str) -> str:
    """使用带密钥的摘要，避免 Redis 泄露后被直接字典反推。"""
    return hmac.new(
        secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class AuthRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        login_global_limit: int | None = None,
        login_ip_limit: int | None = None,
        login_username_limit: int | None = None,
        login_window_seconds: int | None = None,
        register_ip_limit: int | None = None,
        register_username_limit: int | None = None,
        register_window_seconds: int | None = None,
        key_secret: str | None = None,
    ):
        self.redis = redis
        self.login_global_limit = (
            settings.LOGIN_RATE_LIMIT_GLOBAL
            if login_global_limit is None
            else login_global_limit
        )
        self.login_ip_limit = (
            settings.LOGIN_RATE_LIMIT_BY_IP
            if login_ip_limit is None
            else login_ip_limit
        )
        self.login_username_limit = (
            settings.LOGIN_RATE_LIMIT_BY_USERNAME
            if login_username_limit is None
            else login_username_limit
        )
        self.login_window_seconds = (
            settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
            if login_window_seconds is None
            else login_window_seconds
        )
        self.register_ip_limit = (
            settings.REGISTER_RATE_LIMIT_BY_IP
            if register_ip_limit is None
            else register_ip_limit
        )
        self.register_username_limit = (
            settings.REGISTER_RATE_LIMIT_BY_USERNAME
            if register_username_limit is None
            else register_username_limit
        )
        self.register_window_seconds = (
            settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS
            if register_window_seconds is None
            else register_window_seconds
        )
        self.key_secret = (
            key_secret
            or settings.RATE_LIMIT_KEY_SECRET
            or settings.JWT_SECRET_KEY
        )

        numeric_settings = {
            "login_global_limit": self.login_global_limit,
            "login_ip_limit": self.login_ip_limit,
            "login_username_limit": self.login_username_limit,
            "login_window_seconds": self.login_window_seconds,
            "register_ip_limit": self.register_ip_limit,
            "register_username_limit": self.register_username_limit,
            "register_window_seconds": self.register_window_seconds,
        }
        for name, value in numeric_settings.items():
            if value < 1:
                raise ValueError(f"{name} must be greater than zero")
        if len(self.key_secret) < 32:
            raise ValueError("key_secret must contain at least 32 characters")

    async def _enforce(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        try:
            current = await self.redis.eval(
                RATE_LIMIT_SCRIPT,
                1,
                key,
                window_seconds,
            )
        except RedisError as exc:
            # 认证安全组件失败时采用 fail-closed，不能跳过限流。
            raise RateLimitBackendError("认证限流服务暂时不可用") from exc

        if int(current) > limit:
            raise RateLimitExceeded(
                "请求过于频繁，请稍后重试",
                retry_after_seconds=window_seconds,
            )

    def _digest(self, value: str) -> str:
        return digest_key_part(value, self.key_secret)

    async def check_login(self, *, client_ip: str, username: str) -> None:
        ip_part = self._digest(normalize_client_ip(client_ip))
        username_part = self._digest(normalize_username(username))

        # 两个独立桶：防单 IP 扫描大量用户，也防多 IP 攻击一个用户。
        await self._enforce(
            key=f"auth:login:ip:{ip_part}",
            limit=self.login_ip_limit,
            window_seconds=self.login_window_seconds,
        )
        await self._enforce(
            key=f"auth:login:username:{username_part}",
            limit=self.login_username_limit,
            window_seconds=self.login_window_seconds,
        )
        await self._enforce(
            key="auth:login:global",
            limit=self.login_global_limit,
            window_seconds=self.login_window_seconds,
        )

    async def reset_username_after_success(self, username: str) -> None:
        username_part = self._digest(normalize_username(username))
        try:
            await self.redis.delete(f"auth:login:username:{username_part}")
        except RedisError as exc:
            raise RateLimitBackendError("认证限流服务暂时不可用") from exc

    async def check_registration(self, *, client_ip: str, username: str) -> None:
        ip_part = self._digest(normalize_client_ip(client_ip))
        username_part = self._digest(normalize_username(username))
        await self._enforce(
            key=f"auth:register:ip:{ip_part}",
            limit=self.register_ip_limit,
            window_seconds=self.register_window_seconds,
        )
        await self._enforce(
            key=f"auth:register:username:{username_part}",
            limit=self.register_username_limit,
            window_seconds=self.register_window_seconds,
        )
