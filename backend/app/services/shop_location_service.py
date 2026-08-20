from collections.abc import Callable
from datetime import datetime, timezone

from app.schemas.delivery import (
    ShopLocationUpdate,
    StructuredAddress,
)
from app.ports.geocoding import GeocodingPort


class ShopLocationService:
    """供未来店铺新增、修改功能调用的地址编码服务。"""

    def __init__(
        self,
        amap_service: GeocodingPort,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.amap_service = amap_service
        self.now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    async def geocode_shop_address(
        self,
        address: StructuredAddress,
    ) -> ShopLocationUpdate:
        result = await self.amap_service.geocode(address)
        return ShopLocationUpdate(
            address=address,
            longitude=result.longitude,
            latitude=result.latitude,
            adcode=result.adcode,
            formatted_address=result.formatted_address,
            location_updated_at=self.now_provider(),
        )
