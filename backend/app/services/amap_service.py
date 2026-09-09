import hashlib
import hmac

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.observability import metrics as app_metrics
from app.schemas.delivery import GeocodingResult, StructuredAddress


DEFAULT_AMAP_BASE_URL = "https://restapi.amap.com"
AMAP_GEOCODE_URL = f"{DEFAULT_AMAP_BASE_URL}/v3/geocode/geo"
AMAP_REVERSE_GEOCODE_URL = (
    f"{DEFAULT_AMAP_BASE_URL}/v3/geocode/regeo"
)
COARSE_GEOCODING_LEVELS = {
    "省",
    "市",
    "区县",
    "乡镇",
    "村庄",
    "province",
    "city",
    "district",
    "township",
    "village",
}


class AmapServiceError(RuntimeError):
    """高德地理编码服务未能提供可用位置。"""


class AmapServiceUnavailableError(AmapServiceError):
    """高德服务超时、网络失败、限额或鉴权失败。"""


class AmapAddressNotFoundError(AmapServiceError):
    """高德没有找到地址。"""


class AmapAddressAmbiguousError(AmapServiceError):
    """高德返回多个结果或结果精度不足，需要地图选点。"""


class AmapGeocodingService:
    def __init__(
        self,
        *,
        key: str,
        base_url: str = DEFAULT_AMAP_BASE_URL,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        max_retries: int,
        cache_seconds: int,
        cache_secret: str,
        redis: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        if not key:
            raise ValueError("AMap Web service key is required")
        self.key = key
        normalized_base_url = base_url.rstrip("/")
        self.geocode_url = f"{normalized_base_url}/v3/geocode/geo"
        self.reverse_geocode_url = (
            f"{normalized_base_url}/v3/geocode/regeo"
        )
        self.timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self.max_retries = max_retries
        self.cache_seconds = cache_seconds
        self.cache_secret = cache_secret
        self.redis = redis
        self.http_client = http_client

    async def geocode(
        self,
        address: StructuredAddress,
    ) -> GeocodingResult:
        normalized_address = address.full_address().strip()
        cache_key = self._cache_key("geo", normalized_address)
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached

        payload = await self._request_json(
            self.geocode_url,
            {
                "address": normalized_address,
                "city": address.city,
                "output": "JSON",
            },
            operation="geocode",
        )
        geocodes = payload.get("geocodes")
        if not isinstance(geocodes, list) or not geocodes:
            raise AmapAddressNotFoundError("Address was not found")
        if len(geocodes) != 1:
            raise AmapAddressAmbiguousError(
                "Address returned multiple locations"
            )

        geocode = geocodes[0]
        if not isinstance(geocode, dict):
            raise AmapServiceUnavailableError(
                "AMap returned an invalid geocoding result"
            )
        level = str(geocode.get("level", "")).strip().lower()
        if not level or level in COARSE_GEOCODING_LEVELS:
            raise AmapAddressAmbiguousError(
                "Address precision is too coarse"
            )

        longitude, latitude = self._parse_location(
            geocode.get("location")
        )
        result = GeocodingResult(
            longitude=longitude,
            latitude=latitude,
            formatted_address=self._as_text(
                geocode.get("formatted_address")
            ),
            province=self._as_text(geocode.get("province"))
            or address.province,
            city=self._as_text(geocode.get("city")) or address.city,
            district=self._as_text(geocode.get("district"))
            or address.district,
            adcode=self._as_text(geocode.get("adcode")),
        )
        await self._write_cache(cache_key, result)
        return result

    async def reverse_geocode(
        self,
        *,
        longitude: float,
        latitude: float,
    ) -> GeocodingResult:
        normalized_location = f"{longitude:.6f},{latitude:.6f}"
        cache_key = self._cache_key("regeo", normalized_location)
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return cached

        payload = await self._request_json(
            self.reverse_geocode_url,
            {
                "location": normalized_location,
                "extensions": "base",
                "output": "JSON",
            },
            operation="reverse_geocode",
        )
        regeocode = payload.get("regeocode")
        if not isinstance(regeocode, dict) or not regeocode:
            raise AmapAddressNotFoundError(
                "Coordinate could not be reverse geocoded"
            )
        component = regeocode.get("addressComponent")
        if not isinstance(component, dict):
            component = {}

        result = GeocodingResult(
            longitude=round(longitude, 6),
            latitude=round(latitude, 6),
            formatted_address=self._as_text(
                regeocode.get("formatted_address")
            ),
            province=self._as_text(component.get("province")),
            city=self._as_text(component.get("city")),
            district=self._as_text(component.get("district")),
            adcode=self._as_text(component.get("adcode")),
        )
        await self._write_cache(cache_key, result)
        return result

    async def _request_json(
        self,
        url: str,
        params: dict[str, str],
        *,
        operation: str,
    ) -> dict:
        started_at = app_metrics.telemetry.now()
        try:
            payload = await self._request_json_uninstrumented(url, params)
        except Exception as exc:
            app_metrics.telemetry.record_amap_call(
                app_metrics.telemetry.elapsed(started_at),
                operation=operation,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            raise
        app_metrics.telemetry.record_amap_call(
            app_metrics.telemetry.elapsed(started_at),
            operation=operation,
            outcome="succeeded",
        )
        return payload

    async def _request_json_uninstrumented(
        self,
        url: str,
        params: dict[str, str],
    ) -> dict:
        request_params = {**params, "key": self.key}
        for _ in range(self.max_retries + 1):
            try:
                if self.http_client is not None:
                    response = await self.http_client.get(
                        url,
                        params=request_params,
                        timeout=self.timeout,
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=self.timeout
                    ) as client:
                        response = await client.get(
                            url,
                            params=request_params,
                        )
                response.raise_for_status()
                payload = response.json()
            except (
                httpx.HTTPError,
                ValueError,
            ):
                continue

            if not isinstance(payload, dict):
                raise AmapServiceUnavailableError(
                    "AMap returned a non-object response"
                )
            if str(payload.get("status")) != "1":
                infocode = str(payload.get("infocode", "unknown"))
                raise AmapServiceUnavailableError(
                    f"AMap rejected the request ({infocode})"
                )
            return payload

        raise AmapServiceUnavailableError(
            "AMap request failed"
        ) from None

    def _cache_key(self, operation: str, value: str) -> str:
        digest = hmac.new(
            self.cache_secret.encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"amap:{operation}:{digest}"

    async def _read_cache(
        self,
        key: str,
    ) -> GeocodingResult | None:
        if self.redis is None:
            return None
        try:
            cached = await self.redis.get(key)
        except RedisError:
            return None
        if not cached:
            return None
        try:
            return GeocodingResult.model_validate_json(cached)
        except ValueError:
            return None

    async def _write_cache(
        self,
        key: str,
        result: GeocodingResult,
    ) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.setex(
                key,
                self.cache_seconds,
                result.model_dump_json(),
            )
        except RedisError:
            return

    @staticmethod
    def _parse_location(value: object) -> tuple[float, float]:
        if not isinstance(value, str):
            raise AmapServiceUnavailableError(
                "AMap response did not contain a location"
            )
        parts = value.split(",")
        if len(parts) != 2:
            raise AmapServiceUnavailableError(
                "AMap location format is invalid"
            )
        try:
            return round(float(parts[0]), 6), round(float(parts[1]), 6)
        except ValueError as exc:
            raise AmapServiceUnavailableError(
                "AMap location is not numeric"
            ) from exc

    @staticmethod
    def _as_text(value: object) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        return None
