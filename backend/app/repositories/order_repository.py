from motor.motor_asyncio import AsyncIOMotorDatabase


class OrderRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.order_collection = db["orders"]

    async def create_order(self, order_data: dict):
        result = await self.order_collection.insert_one(order_data)
        return result.inserted_id