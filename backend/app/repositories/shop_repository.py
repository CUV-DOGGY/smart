from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorDatabase,
)

from app.schemas.shop import Shop


class ShopRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.shop_collection = db["shops"]

    async def find_by_shop_id(
        self,
        shop_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> Shop | None:
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
            },
            session=session,
        )
        if document is None:
            return None
        return Shop.model_validate(document)
