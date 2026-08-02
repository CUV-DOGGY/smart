from collections.abc import Awaitable, Callable
from typing import TypeVar

from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorDatabase,
)
from pymongo.errors import DuplicateKeyError

from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)


_T = TypeVar("_T")


class OrderUniquenessConflictError(RuntimeError):
    """订单唯一标识或幂等键发生数据库唯一索引冲突。"""


class OrderRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.order_collection = db["orders"]

    async def ensure_indexes(self) -> None:
        await self.order_collection.create_index(
            [("order_id", 1)],
            unique=True,
            name="uq_order_id",
        )
        await self.order_collection.create_index(
            [
                ("user_id", 1),
                ("idempotency_key", 1),
            ],
            unique=True,
            partialFilterExpression={
                "idempotency_key": {"$type": "string"},
            },
            name="uq_user_order_idempotency_key",
        )

    async def run_in_transaction(
        self,
        callback: Callable[[AsyncIOMotorClientSession], Awaitable[_T]],
    ) -> _T:
        client = self.order_collection.database.client
        try:
            async with await client.start_session() as session:
                return await session.with_transaction(callback)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB transaction is temporarily unavailable"
            ) from exc

    async def create_order(
        self,
        order_data: dict,
        session: AsyncIOMotorClientSession | None = None,
    ):
        try:
            result = await self.order_collection.insert_one(
                order_data,
                session=session,
            )
        except DuplicateKeyError as exc:
            raise OrderUniquenessConflictError(
                "Order unique identifier already exists"
            ) from exc
        return result.inserted_id

    async def find_by_idempotency_key(
        self,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> dict | None:
        try:
            return await self.order_collection.find_one(
                {
                    "user_id": user_id,
                    "idempotency_key": idempotency_key,
                },
                {"_id": 0},
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order lookup is temporarily unavailable"
            ) from exc
   
    async def query_order_by_id(self, order_id: str,user_id:str):
        result = await self.order_collection.find_one({"order_id": order_id,
        "user_id": user_id}, {"_id": 0})
        return result
    
    async def query_order_status(self, order_id: str, user_id: str):
        try:
            return await self.order_collection.find_one(
                {
                    "order_id": order_id,
                    "user_id": user_id,
                },
                {"_id": 0, "order_status": 1},
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order status lookup is temporarily unavailable"
            ) from exc
        
    async def query_order_history(self, user_id: str):
        result = await self.order_collection.find(
            {"user_id":user_id},{"_id":0})\
            .sort("create_time",-1)\
            .to_list(length=None)
        return result


    async def cancel_order(
        self,
        order_id: str,
        user_id: str,
        expected_status: str,
        target_status: str,
    ) -> bool:
        try:
            result = await self.order_collection.update_one(
                {
                    "order_id": order_id,
                    "user_id": user_id,
                    "order_status": expected_status,
                },
                {"$set": {"order_status": target_status}},
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order cancellation is temporarily unavailable"
            ) from exc
        return result.modified_count == 1
