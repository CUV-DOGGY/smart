import hashlib
import hmac

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings


RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class TelemetryRateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("浏览器遥测上报过于频繁")
        self.retry_after_seconds = retry_after_seconds


class TelemetryRateLimitBackendError(RuntimeError):
    """Redis 不可用时采用 fail-closed，避免绕过遥测入口限流。"""


class TelemetryRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
        key_secret: str | None = None,
    ) -> None:
        self.redis = redis
        self.limit = (
            settings.BROWSER_TELEMETRY_RATE_LIMIT_BY_USER
            if limit is None
            else limit
        )
        self.window_seconds = (
            settings.BROWSER_TELEMETRY_RATE_LIMIT_WINDOW_SECONDS
            if window_seconds is None
            else window_seconds
        )
        self.key_secret = (
            key_secret
            or settings.RATE_LIMIT_KEY_SECRET
            or settings.JWT_SECRET_KEY
        )

    async def check(self, user_id: str) -> None:
        user_digest = hmac.new(
            self.key_secret.encode("utf-8"),
            user_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        try:
            current = await self.redis.eval(
                RATE_LIMIT_SCRIPT,
                1,
                f"telemetry:traces:user:{user_digest}",
                self.window_seconds,
            )
        except RedisError as exc:
            raise TelemetryRateLimitBackendError(
                "浏览器遥测限流服务不可用"
            ) from exc

        if int(current) > self.limit:
            raise TelemetryRateLimitExceeded(self.window_seconds)
