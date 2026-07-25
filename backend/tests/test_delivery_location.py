import unittest
import logging
from datetime import datetime, time, timezone

import httpx
from pydantic import ValidationError

from app.schemas.delivery import (
    DeliveryAddressInput,
    GeocodingResult,
    StructuredAddress,
)
from app.schemas.shop import Shop
from app.core.logger import SensitiveQueryParameterFilter
from app.services.amap_service import (
    AMAP_GEOCODE_URL,
    AmapAddressAmbiguousError,
    AmapGeocodingService,
    AmapServiceUnavailableError,
)
from app.services.delivery_location_service import (
    AddressNeedsMapPickError,
    DeliveryLocationService,
    OutsideDeliveryAreaError,
    ShopDeliveryConfigurationError,
    haversine_distance_meters,
)
from app.services.delivery_geocoding_rate_limiter import (
    DeliveryGeocodingRateLimitExceeded,
    DeliveryGeocodingRateLimiter,
)
from app.services.shop_location_service import ShopLocationService


class FakeAmapService:
    def __init__(
        self,
        *,
        geocoding_result: GeocodingResult | None = None,
        error: Exception | None = None,
    ):
        self.geocoding_result = geocoding_result or GeocodingResult(
            longitude=116.001,
            latitude=39.0,
            formatted_address="北京市朝阳区测试路1号",
            province="北京市",
            city="北京市",
            district="朝阳区",
            adcode="110105",
        )
        self.error = error

    async def geocode(self, address):
        if self.error is not None:
            raise self.error
        return self.geocoding_result

    async def reverse_geocode(self, *, longitude: float, latitude: float):
        if self.error is not None:
            raise self.error
        return self.geocoding_result.model_copy(
            update={
                "longitude": longitude,
                "latitude": latitude,
            }
        )


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def eval(self, script, number_of_keys, key, window):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def make_address(**overrides) -> DeliveryAddressInput:
    data = {
        "province": "北京市",
        "city": "北京市",
        "district": "朝阳区",
        "detail_address": "测试路1号",
    }
    data.update(overrides)
    return DeliveryAddressInput(**data)


def make_shop(**overrides) -> Shop:
    data = {
        "shop_id": "shop-001",
        "shop_name": "Test shop",
        "is_active": True,
        "is_accepting_orders": True,
        "timezone": "UTC",
        "business_hours": [
            {
                "day_of_week": 0,
                "open_time": time(0, 0),
                "close_time": time(23, 59),
            }
        ],
        "minimum_order_amount": 0,
        "delivery_fee": 0,
        "longitude": 116.0,
        "latitude": 39.0,
        "delivery_radius_meters": 5000,
    }
    data.update(overrides)
    return Shop(**data)


class DeliveryAddressSchemaTests(unittest.TestCase):
    def test_coordinates_must_be_submitted_as_a_pair(self):
        with self.assertRaises(ValidationError):
            make_address(longitude=116.0)

    def test_removes_repeated_administrative_prefix(self):
        address = DeliveryAddressInput(
            province="广东省",
            city="深圳市",
            district="南山区",
            detail_address="广东省深圳市南山区科技园1号",
        )

        self.assertEqual(address.detail_address, "科技园1号")
        self.assertEqual(
            address.full_address(),
            "广东省深圳市南山区科技园1号",
        )

    def test_removes_direct_municipality_prefix_without_duplication(self):
        address = DeliveryAddressInput(
            province="北京市",
            city="北京市",
            district="朝阳区",
            detail_address="北京市北京市朝阳区测试路1号",
        )

        self.assertEqual(address.detail_address, "测试路1号")
        self.assertEqual(
            address.full_address(),
            "北京市朝阳区测试路1号",
        )

    def test_removes_partial_prefix_and_separators(self):
        address = DeliveryAddressInput(
            province="广东省",
            city="深圳市",
            district="南山区",
            detail_address="深圳市，南山区，科技园1号",
        )

        self.assertEqual(address.detail_address, "科技园1号")

    def test_rejects_detail_containing_only_administrative_areas(self):
        with self.assertRaises(ValidationError):
            DeliveryAddressInput(
                province="广东省",
                city="深圳市",
                district="南山区",
                detail_address="广东省深圳市南山区",
            )


class SensitiveLoggingTests(unittest.TestCase):
    def test_amap_key_is_redacted_from_request_log(self):
        record = logging.LogRecord(
            name="httpx",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=(
                "HTTP Request: GET "
                "https://restapi.amap.com/v3/geocode/geo?"
                "address=test&key=secret-key"
            ),
            args=(),
            exc_info=None,
        )

        SensitiveQueryParameterFilter().filter(record)

        self.assertNotIn("secret-key", record.getMessage())
        self.assertIn("key=***", record.getMessage())


class DeliveryGeocodingRateLimiterTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_limits_geocoding_by_hashed_user_id(self):
        redis = FakeRedis()
        limiter = DeliveryGeocodingRateLimiter(
            redis,
            limit=1,
            window_seconds=60,
            key_secret="s" * 32,
        )

        await limiter.check("sensitive-user-id")
        with self.assertRaises(DeliveryGeocodingRateLimitExceeded):
            await limiter.check("sensitive-user-id")

        serialized_keys = " ".join(redis.counts)
        self.assertNotIn("sensitive-user-id", serialized_keys)


class DeliveryLocationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_geocodes_text_address_and_builds_snapshot(self):
        service = DeliveryLocationService(FakeAmapService())
        address = make_address()

        resolved = await service.resolve(address)
        snapshot = service.build_snapshot(
            address=address,
            resolved=resolved,
            shop=make_shop(),
        )

        self.assertEqual(resolved.location_source, "geocoded")
        self.assertEqual(resolved.verification_status, "verified")
        self.assertGreater(snapshot.distance_meters, 0)
        self.assertEqual(snapshot.delivery_radius_meters_snapshot, 5000)

    async def test_text_address_needs_map_pick_when_ambiguous(self):
        service = DeliveryLocationService(
            FakeAmapService(error=AmapAddressAmbiguousError("ambiguous"))
        )

        with self.assertRaises(AddressNeedsMapPickError):
            await service.resolve(make_address())

    async def test_map_pick_degrades_when_amap_is_unavailable(self):
        service = DeliveryLocationService(
            FakeAmapService(
                error=AmapServiceUnavailableError("unavailable")
            )
        )

        resolved = await service.resolve(
            make_address(longitude=116.001, latitude=39.0)
        )

        self.assertEqual(resolved.location_source, "map_pick")
        self.assertEqual(resolved.verification_status, "unverified")
        self.assertEqual(resolved.longitude, 116.001)

    async def test_text_address_does_not_degrade_without_coordinates(self):
        service = DeliveryLocationService(
            FakeAmapService(
                error=AmapServiceUnavailableError("unavailable")
            )
        )

        with self.assertRaises(AmapServiceUnavailableError):
            await service.resolve(make_address())

    async def test_rejects_location_outside_delivery_radius(self):
        service = DeliveryLocationService(
            FakeAmapService(
                geocoding_result=GeocodingResult(
                    longitude=117.0,
                    latitude=40.0,
                )
            )
        )
        address = make_address()
        resolved = await service.resolve(address)

        with self.assertRaises(OutsideDeliveryAreaError):
            service.build_snapshot(
                address=address,
                resolved=resolved,
                shop=make_shop(),
            )

    async def test_rejects_shop_without_delivery_configuration(self):
        service = DeliveryLocationService(FakeAmapService())
        address = make_address()
        resolved = await service.resolve(address)

        with self.assertRaises(ShopDeliveryConfigurationError):
            service.build_snapshot(
                address=address,
                resolved=resolved,
                shop=make_shop(
                    longitude=None,
                    latitude=None,
                    delivery_radius_meters=None,
                ),
            )

    def test_zero_distance_is_inside_boundary(self):
        distance = haversine_distance_meters(
            origin_longitude=116.0,
            origin_latitude=39.0,
            destination_longitude=116.0,
            destination_latitude=39.0,
        )
        self.assertEqual(distance, 0)


class AmapGeocodingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_official_geocoding_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(str(request.url).split("?")[0], AMAP_GEOCODE_URL)
            self.assertEqual(request.url.params["key"], "test-key")
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "count": "1",
                    "geocodes": [
                        {
                            "formatted_address": "北京市朝阳区测试路1号",
                            "province": "北京市",
                            "city": "北京市",
                            "district": "朝阳区",
                            "adcode": "110105",
                            "location": "116.001000,39.000000",
                            "level": "门牌号",
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            service = AmapGeocodingService(
                key="test-key",
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                max_retries=0,
                cache_seconds=60,
                cache_secret="s" * 32,
                http_client=client,
            )
            result = await service.geocode(
                StructuredAddress(
                    province="北京市",
                    city="北京市",
                    district="朝阳区",
                    detail_address="测试路1号",
                )
            )

        self.assertEqual(result.longitude, 116.001)
        self.assertEqual(result.adcode, "110105")

    async def test_rejects_coarse_geocoding_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "count": "1",
                    "geocodes": [
                        {
                            "location": "116.0,39.0",
                            "level": "区县",
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            service = AmapGeocodingService(
                key="test-key",
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                max_retries=0,
                cache_seconds=60,
                cache_secret="s" * 32,
                http_client=client,
            )
            with self.assertRaises(AmapAddressAmbiguousError):
                await service.geocode(
                    StructuredAddress(
                        province="北京市",
                        city="北京市",
                        district="朝阳区",
                        detail_address="测试",
                    )
                )


class ShopLocationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_fields_for_future_shop_persistence(self):
        now = datetime(2026, 7, 25, tzinfo=timezone.utc)
        service = ShopLocationService(
            FakeAmapService(),
            now_provider=lambda: now,
        )
        address = StructuredAddress(
            province="北京市",
            city="北京市",
            district="朝阳区",
            detail_address="测试路1号",
        )

        result = await service.geocode_shop_address(address)

        self.assertEqual(result.longitude, 116.001)
        self.assertEqual(result.adcode, "110105")
        self.assertEqual(result.location_updated_at, now)


if __name__ == "__main__":
    unittest.main()
