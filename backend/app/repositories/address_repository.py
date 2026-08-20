from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorDatabase,
)
from pymongo import ReturnDocument

from app.schemas.address import UserAddress

from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)

_T = TypeVar("_T")

ADDRESS_PROJECTION = {
    "_id": 0,
    "address_id": 1,
    "user_id": 1,
    "receiver_name": 1,
    "receiver_phone": 1,
    "province": 1,
    "city": 1,
    "district": 1,
    "detail_address": 1,
    "longitude": 1,
    "latitude": 1,
    "formatted_address": 1,
    "adcode": 1,
    "location_source": 1,
    "verification_status": 1,
    "is_default": 1,
    "version": 1,
    "is_deleted": 1,
    "create_time": 1,
    "update_time": 1,
}


class AddressRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.address_collection = db["user_addresses"]
        self.user_collection = db["users"]

    async def ensure_indexes(self) -> None:
        await self.address_collection.create_index(
            [("address_id", 1)],
            unique=True,
            name="uq_address_id",
        )
        await self.address_collection.create_index(
            [
                ("user_id", 1),
                ("is_deleted", 1),
                ("is_default", -1),
                ("update_time", -1),
            ],
            name="idx_user_active_addresses",
        )
        await self.address_collection.create_index(
            [("user_id", 1), ("is_default", 1)],
            unique=True,
            partialFilterExpression={
                "is_default": True,
                "is_deleted": False,
            },
            name="uq_user_default_address",
        )

    async def run_in_transaction(
        self,
        callback: Callable[[AsyncIOMotorClientSession], Awaitable[_T]],
    ) -> _T:
        client = self.address_collection.database.client
        try:
            async with await client.start_session() as session:
                return await session.with_transaction(callback)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB transaction is temporarily unavailable"
            ) from exc

    async def acquire_user_address_lock(
        self,
        *,
        user_id: str,
        session: AsyncIOMotorClientSession,
    ) -> None:
        result = await self.user_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"address_mutation_version": 1}},
            session=session,
        )
        if result.matched_count != 1:
            raise RuntimeError("Authenticated user no longer exists")

    async def count_active(
        self,
        *,
        user_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> int:
        return await self.address_collection.count_documents(
            {
                "user_id": user_id,
                "is_deleted": False,
            },
            session=session,
        )

    async def create_address(
        self,
        address_data: dict,
        *,
        session: AsyncIOMotorClientSession,
    ) -> None:
        await self.address_collection.insert_one(
            address_data,
            session=session,
        )

    async def find_by_id(
        self,
        *,
        user_id: str,
        address_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> UserAddress | None:
        try:
            document = await self.address_collection.find_one(
                {
                    "address_id": address_id,
                    "user_id": user_id,
                    "is_deleted": False,
                },
                ADDRESS_PROJECTION,
                session=session,
            )
            if document is None:
                return None
            return UserAddress.model_validate(document)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB address lookup is temporarily unavailable"
            ) from exc

    async def list_active(self, user_id: str) -> list[UserAddress]:
        documents = (
            await self.address_collection.find(
                {
                    "user_id": user_id,
                    "is_deleted": False,
                },
                ADDRESS_PROJECTION,
            )
            .sort(
                [
                    ("is_default", -1),
                    ("update_time", -1),
                ]
            )
            .to_list(length=15)
        )
        return [UserAddress.model_validate(document) for document in documents]

    async def update_address(
        self,
        *,
        user_id: str,
        address_id: str,
        update_data: dict,
        session: AsyncIOMotorClientSession,
    ) -> UserAddress | None:
        document = await self.address_collection.find_one_and_update(
            {
                "address_id": address_id,
                "user_id": user_id,
                "is_deleted": False,
            },
            {
                "$set": update_data,
                "$inc": {"version": 1},
            },
            projection=ADDRESS_PROJECTION,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if document is None:
            return None
        return UserAddress.model_validate(document)

    async def clear_default(
        self,
        *,
        user_id: str,
        update_time: datetime,
        session: AsyncIOMotorClientSession,
    ) -> None:
        await self.address_collection.update_many(
            {
                "user_id": user_id,
                "is_deleted": False,
                "is_default": True,
            },
            {
                "$set": {
                    "is_default": False,
                    "update_time": update_time,
                },
                "$inc": {"version": 1},
            },
            session=session,
        )

    async def set_default(
        self,
        *,
        user_id: str,
        address_id: str,
        update_time: datetime,
        session: AsyncIOMotorClientSession,
    ) -> bool:
        result = await self.address_collection.update_one(
            {
                "address_id": address_id,
                "user_id": user_id,
                "is_deleted": False,
            },
            {
                "$set": {
                    "is_default": True,
                    "update_time": update_time,
                },
                "$inc": {"version": 1},
            },
            session=session,
        )
        return result.matched_count == 1

    async def soft_delete(
        self,
        *,
        user_id: str,
        address_id: str,
        update_time: datetime,
        session: AsyncIOMotorClientSession,
    ) -> UserAddress | None:
        document = await self.address_collection.find_one_and_update(
            {
                "address_id": address_id,
                "user_id": user_id,
                "is_deleted": False,
            },
            {
                "$set": {
                    "is_deleted": True,
                    "is_default": False,
                    "update_time": update_time,
                },
                "$inc": {"version": 1},
            },
            projection=ADDRESS_PROJECTION,
            return_document=ReturnDocument.BEFORE,
            session=session,
        )
        if document is None:
            return None
        return UserAddress.model_validate(document)

    async def find_latest_active(
        self,
        *,
        user_id: str,
        session: AsyncIOMotorClientSession,
    ) -> UserAddress | None:
        document = await self.address_collection.find_one(
            {
                "user_id": user_id,
                "is_deleted": False,
            },
            ADDRESS_PROJECTION,
            sort=[("update_time", -1)],
            session=session,
        )
        if document is None:
            return None
        return UserAddress.model_validate(document)
