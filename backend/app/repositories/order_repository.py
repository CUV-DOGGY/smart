from motor.motor_asyncio import AsyncIOMotorDatabase


class OrderRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.order_collection = db["orders"]

    async def create_order(self, order_data: dict):
        result = await self.order_collection.insert_one(order_data)
        return result.inserted_id
   
    async def query_order_by_id(self, order_id: str,user_id:str):
        result = await self.order_collection.find_one({"order_id": order_id,
        "user_id": user_id}, {"_id": 0})
        return result
    
    async def query_order_status(self, order_id: str, user_id: str):
        result = await self.order_collection.find_one({"order_id": order_id,
        "user_id": user_id}, {"_id": 0, "order_status": 1})
        return result
        
    async def query_order_history(self, user_id: str):
        result = await self.order_collection.find(
            {"user_id":user_id},{"_id":0})\
            .sort("create_time",-1)\
            .to_list(length=None)
        return result


    async def cancel_order(self, order_id: str, user_id: str, status: str):
        result = await self.order_collection.update_one(
            {"order_id": order_id, "user_id": user_id},
            {"$set": {"order_status": status}}
        )
        return result.modified_count == 1