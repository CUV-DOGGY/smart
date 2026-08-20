import base64
import binascii
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
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
        try:
            result = await self.order_collection.find_one({"order_id": order_id,
            "user_id": user_id}, {"_id": 0})
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order lookup is temporarily unavailable"
            ) from exc
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
        try:
            result = await self.order_collection.find(
                {"user_id":user_id},{"_id":0})\
                .sort("create_time",-1)\
                .to_list(length=None)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order history is temporarily unavailable"
            ) from exc
        return result

    async def query_order_history_page(
        self,
        user_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        filters: dict = {"user_id": user_id}
        if cursor:
            create_time, order_id = self._decode_cursor(cursor)
            filters["$or"] = [
                {"create_time": {"$lt": create_time}},
                {
                    "create_time": create_time,
                    "order_id": {"$lt": order_id},
                },
            ]
        try:
            documents = await self.order_collection.find(
                filters,
                {"_id": 0},
            ).sort([("create_time", -1), ("order_id", -1)]).to_list(
                length=limit + 1
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB order history is temporarily unavailable"
            ) from exc
        has_more = len(documents) > limit
        items = documents[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = self._encode_cursor(
                last["create_time"],
                last["order_id"],
            )
        return items, next_cursor

    @staticmethod
    def _encode_cursor(create_time: datetime, order_id: str) -> str:
        payload = json.dumps(
            [create_time.isoformat(), order_id],
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        try:
            padding = "=" * (-len(cursor) % 4)
            timestamp, order_id = json.loads(
                base64.urlsafe_b64decode(cursor + padding)
            )
            create_time = datetime.fromisoformat(timestamp)
            if create_time.tzinfo is None or not order_id:
                raise ValueError
            return create_time, str(order_id)
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
            raise ValueError("Invalid order cursor") from exc


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
