from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.services.auth_rate_limiter import (
    RATE_LIMIT_SCRIPT,
    digest_key_part,
)


class DeliveryGeocodingRateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Delivery geocoding rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class DeliveryGeocodingRateLimitBackendError(RuntimeError):
    """无法安全执行地址解析限流。"""


class DeliveryGeocodingRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
        key_secret: str | None = None,
    ):
        self.redis = redis
        self.limit = (
            settings.ORDER_GEOCODE_RATE_LIMIT_BY_USER
            if limit is None
            else limit
        )
        self.window_seconds = (
            settings.ORDER_GEOCODE_RATE_LIMIT_WINDOW_SECONDS
            if window_seconds is None
            else window_seconds
        )
        self.key_secret = (
            key_secret
            or settings.RATE_LIMIT_KEY_SECRET
            or settings.JWT_SECRET_KEY
        )

    async def check(self, user_id: str) -> None:
        user_part = digest_key_part(user_id, self.key_secret)
        try:
            current = await self.redis.eval(
                RATE_LIMIT_SCRIPT,
                1,
                f"orders:geocode:user:{user_part}",
                self.window_seconds,
            )
        except RedisError as exc:
            raise DeliveryGeocodingRateLimitBackendError(
                "Delivery geocoding rate limiter is unavailable"
            ) from exc
        if int(current) > self.limit:
            raise DeliveryGeocodingRateLimitExceeded(
                self.window_seconds
            )
