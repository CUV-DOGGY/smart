from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorDatabase,
)

from app.schemas.shop import Shop
from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)


class ShopRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.shop_collection = db["shops"]

    async def ensure_indexes(self) -> None:
        try:
            await self.shop_collection.create_index(
                [("shop_id", 1)],
                unique=True,
                name="uq_shop_id",
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB shop index initialization failed"
            ) from exc

    async def list_active(self, limit: int = 100) -> list[Shop]:
        try:
            documents = await self.shop_collection.find(
                {
                    "is_active": True,
                },
                {"_id": 0},
            ).sort("shop_name", 1).to_list(length=limit)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB shop listing is temporarily unavailable"
            ) from exc
        return [Shop.model_validate(document) for document in documents]

    async def find_by_shop_id(
        self,
        shop_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> Shop | None:
        try:
            document = await self.shop_collection.find_one(
                {"shop_id": shop_id},
                {
                    "_id": 0,
                    "shop_id": 1,
                    "shop_name": 1,
                    "is_active": 1,
                    "is_accepting_orders": 1,
                    "timezone": 1,
                    "business_hours": 1,
                    "minimum_order_amount": 1,
                    "delivery_fee": 1,
                    "address": 1,
                    "longitude": 1,
                    "latitude": 1,
                    "adcode": 1,
                    "formatted_address": 1,
                    "delivery_radius_meters": 1,
                    "location_updated_at": 1,
                },
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB shop lookup is temporarily unavailable"
            ) from exc
        if document is None:
            return None
        return Shop.model_validate(document)
