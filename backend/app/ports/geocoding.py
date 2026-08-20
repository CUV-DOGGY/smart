from typing import Protocol

from app.schemas.delivery import GeocodingResult, StructuredAddress


class GeocodingPort(Protocol):
    async def geocode(self, address: StructuredAddress) -> GeocodingResult: ...
    async def reverse_geocode(self, *, longitude: float, latitude: float) -> GeocodingResult: ...
