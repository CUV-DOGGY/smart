import math

from app.schemas.delivery import (
    DeliveryAddressInput,
    DeliveryLocationSnapshot,
    ResolvedDeliveryLocation,
)
from app.schemas.shop import Shop
from app.ports.geocoding import GeocodingPort
from app.services.amap_service import (
    AmapAddressAmbiguousError,
    AmapAddressNotFoundError,
    AmapServiceError,
)


EARTH_RADIUS_METERS = 6_371_000


class AddressNeedsMapPickError(RuntimeError):
    """文字地址无法得到唯一、足够精确的位置。"""


class ShopDeliveryConfigurationError(RuntimeError):
    """店铺没有完整的坐标或配送半径配置。"""


class OutsideDeliveryAreaError(RuntimeError):
    """收货位置超出店铺配送半径。"""

    def __init__(
        self,
        *,
        distance_meters: int,
        delivery_radius_meters: int,
    ) -> None:
        super().__init__("Delivery address is outside the delivery area")
        self.distance_meters = distance_meters
        self.delivery_radius_meters = delivery_radius_meters


class DeliveryLocationService:
    def __init__(
        self,
        amap_service: GeocodingPort | None = None,
    ):
        self.amap_service = amap_service

    async def resolve(
        self,
        address: DeliveryAddressInput,
    ) -> ResolvedDeliveryLocation:
        if self.amap_service is None:
            raise RuntimeError(
                "AMap service is required to resolve an address"
            )
        if address.longitude is not None and address.latitude is not None:
            longitude = round(address.longitude, 6)
            latitude = round(address.latitude, 6)
            try:
                geocoded = await self.amap_service.reverse_geocode(
                    longitude=longitude,
                    latitude=latitude,
                )
            except AmapServiceError:
                return ResolvedDeliveryLocation(
                    longitude=longitude,
                    latitude=latitude,
                    formatted_address=address.full_address(),
                    province=address.province,
                    city=address.city,
                    district=address.district,
                    adcode=None,
                    location_source="map_pick",
                    verification_status="unverified",
                )
            resolved_data = geocoded.model_dump()
            resolved_data.update({
                "province": geocoded.province or address.province,
                "city": geocoded.city or address.city,
                "district": geocoded.district or address.district,
                "location_source": "map_pick",
                "verification_status": "verified",
            })
            return ResolvedDeliveryLocation(**resolved_data)

        try:
            geocoded = await self.amap_service.geocode(address)
        except (
            AmapAddressNotFoundError,
            AmapAddressAmbiguousError,
        ) as exc:
            raise AddressNeedsMapPickError(
                "Address needs a map-selected location"
            ) from exc

        return ResolvedDeliveryLocation(
            **geocoded.model_dump(),
            location_source="geocoded",
            verification_status="verified",
        )

    def build_snapshot(
        self,
        *,
        address: DeliveryAddressInput,
        resolved: ResolvedDeliveryLocation,
        shop: Shop,
    ) -> DeliveryLocationSnapshot:
        self.validate_shop_configuration(shop)
        distance_meters = math.ceil(
            haversine_distance_meters(
                origin_longitude=shop.longitude,
                origin_latitude=shop.latitude,
                destination_longitude=resolved.longitude,
                destination_latitude=resolved.latitude,
            )
        )
        if distance_meters > shop.delivery_radius_meters:
            raise OutsideDeliveryAreaError(
                distance_meters=distance_meters,
                delivery_radius_meters=shop.delivery_radius_meters,
            )

        snapshot_data = resolved.model_dump()
        snapshot_data.update({
            "province": resolved.province or address.province,
            "city": resolved.city or address.city,
            "district": resolved.district or address.district,
            "detail_address": address.detail_address,
            "distance_meters": distance_meters,
            "delivery_radius_meters_snapshot": (
                shop.delivery_radius_meters
            ),
        })
        return DeliveryLocationSnapshot(**snapshot_data)

    @staticmethod
    def validate_shop_configuration(shop: Shop) -> None:
        if (
            shop.longitude is None
            or shop.latitude is None
            or shop.delivery_radius_meters is None
        ):
            raise ShopDeliveryConfigurationError(
                "Shop delivery location is not configured"
            )


def haversine_distance_meters(
    *,
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
) -> float:
    origin_latitude_radians = math.radians(origin_latitude)
    destination_latitude_radians = math.radians(destination_latitude)
    latitude_delta = math.radians(
        destination_latitude - origin_latitude
    )
    longitude_delta = math.radians(
        destination_longitude - origin_longitude
    )

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_latitude_radians)
        * math.cos(destination_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return (
        2
        * EARTH_RADIUS_METERS
        * math.asin(min(1.0, math.sqrt(haversine)))
    )
