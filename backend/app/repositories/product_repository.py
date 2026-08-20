from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorDatabase,
)

from app.schemas.product import Product
from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)


class ProductRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.product_collection = db["products"]

    async def ensure_indexes(self) -> None:
        try:
            await self.product_collection.create_index(
                [("shop_id", 1), ("food_id", 1)],
                unique=True,
                name="uq_shop_food_id",
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB product index initialization failed"
            ) from exc

    async def list_available_by_shop(
        self,
        shop_id: str,
        limit: int = 200,
    ) -> list[Product]:
        try:
            documents = await self.product_collection.find(
                {
                    "shop_id": shop_id,
                    "is_listed": True,
                    "is_available": True,
                },
                {"_id": 0},
            ).sort("food_name", 1).to_list(length=limit)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB product listing is temporarily unavailable"
            ) from exc
        return [Product.model_validate(document) for document in documents]

    async def find_by_shop_and_food_ids(
        self,
        shop_id: str,
        food_ids: list[str],
        session: AsyncIOMotorClientSession | None = None,
    ) -> list[Product]:
        try:
            documents = await self.product_collection.find(
                {
                    "shop_id": shop_id,
                    "food_id": {"$in": food_ids},
                },
                {
                    "_id": 0,
                    "food_id": 1,
                    "shop_id": 1,
                    "food_name": 1,
                    "price": 1,
                    "stock": 1,
                    "is_listed": 1,
                    "is_available": 1,
                },
                session=session,
            ).to_list(length=len(food_ids))
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB product lookup is temporarily unavailable"
            ) from exc
        return [Product.model_validate(document) for document in documents]

    async def reserve_stock(
        self,
        *,
        product: Product,
        quantity: int,
        session: AsyncIOMotorClientSession,
    ) -> bool:
        try:
            result = await self.product_collection.update_one(
                {
                    "food_id": product.food_id,
                    "shop_id": product.shop_id,
                    "price": product.price,
                    "is_listed": True,
                    "is_available": True,
                    "stock": {"$gte": quantity},
                },
                {
                    "$inc": {
                        "stock": -quantity,
                        "reserved_stock": quantity,
                    }
                },
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB stock reservation is temporarily unavailable"
            ) from exc
        return result.modified_count == 1
