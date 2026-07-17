from motor.motor_asyncio import AsyncIOMotorDatabase


class OrderRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.order_collection = db["orders"]

    async def create_order(self, order_data: dict):
        result = await self.order_collection.insert_one(order_data)
        return result.inserted_id
   
    async def query_order_by_id(self, order_id: str,user_id:str):
        result = await self.order_collection.find_one({"order_id": order_id,
        "user_id": user_id})
        return result