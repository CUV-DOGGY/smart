from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.config import settings
from app.dependencies.cache import get_redis
from app.services.amap_service import AmapGeocodingService
from app.services.delivery_geocoding_rate_limiter import (
    DeliveryGeocodingRateLimiter,
)
from app.services.delivery_location_service import DeliveryLocationService


def get_amap_geocoding_service(
    redis: Annotated[Redis, Depends(get_redis)],
) -> AmapGeocodingService:
    return AmapGeocodingService(
        key=settings.AMAP_WEB_SERVICE_KEY.get_secret_value(),
        base_url=settings.AMAP_BASE_URL,
        connect_timeout_seconds=settings.AMAP_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=settings.AMAP_READ_TIMEOUT_SECONDS,
        max_retries=settings.AMAP_MAX_RETRIES,
        cache_seconds=settings.AMAP_GEOCODE_CACHE_SECONDS,
        cache_secret=(
            settings.RATE_LIMIT_KEY_SECRET
            or settings.JWT_SECRET_KEY
        ),
        redis=redis,
    )


def get_delivery_location_service(
    amap_service: Annotated[
        AmapGeocodingService,
        Depends(get_amap_geocoding_service),
    ],
) -> DeliveryLocationService:
    return DeliveryLocationService(amap_service)


def get_delivery_geocoding_rate_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
) -> DeliveryGeocodingRateLimiter:
    return DeliveryGeocodingRateLimiter(redis)
