from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas.order import Product


class ProductRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.product_collection = db["products"]

    async def find_by_food_ids(self, food_ids: list[str]) -> list[Product]:
        documents = await self.product_collection.find(
            {"food_id": {"$in": food_ids}},
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
        ).to_list(length=len(food_ids))
        return [Product.model_validate(document) for document in documents]
