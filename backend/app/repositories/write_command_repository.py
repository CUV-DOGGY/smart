from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.constants.write_command_status import WriteCommandStatus
from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)


_T = TypeVar("_T")


class WriteCommandRepository:
    def __init__(self, db: AsyncDatabase):
        self.collection = db["write_commands"]

    async def ensure_indexes(self) -> None:
        try:
            await self.collection.create_index(
                [("command_id", 1)],
                unique=True,
                name="uq_write_command_id",
            )
            await self.collection.create_index(
                [("user_id", 1), ("decision_idempotency_key", 1)],
                unique=True,
                partialFilterExpression={
                    "decision_idempotency_key": {"$type": "string"}
                },
                name="uq_user_write_decision_idempotency_key",
            )
            await self.collection.create_index(
                [
                    ("user_id", 1),
                    ("conversation_id", 1),
                    ("status", 1),
                    ("created_at", -1),
                ],
                name="idx_conversation_write_commands",
            )
            await self.collection.create_index(
                [("status", 1), ("next_attempt_at", 1), ("lease_until", 1)],
                name="idx_write_command_worker",
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command index initialization failed"
            ) from exc

    async def run_in_transaction(
        self,
        callback: Callable[[AsyncClientSession], Awaitable[_T]],
    ) -> _T:
        client = self.collection.database.client
        try:
            async with client.start_session() as session:
                return await session.with_transaction(callback)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command transaction is temporarily unavailable"
            ) from exc

    async def create(self, document: dict[str, Any]) -> dict[str, Any]:
        try:
            await self.collection.insert_one(document)
            return document
        except DuplicateKeyError:
            existing = await self.find_by_command_id(document["command_id"])
            if existing is None:
                raise
            return existing
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command creation is temporarily unavailable"
            ) from exc

    async def find_by_command_id(
        self,
        command_id: str,
        *,
        session: AsyncClientSession | None = None,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one(
                {"command_id": command_id},
                {"_id": 0},
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command lookup is temporarily unavailable"
            ) from exc

    async def find_owned(
        self,
        *,
        command_id: str,
        user_id: str,
        session: AsyncClientSession | None = None,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one(
                {"command_id": command_id, "user_id": user_id},
                {"_id": 0},
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command lookup is temporarily unavailable"
            ) from exc

    async def find_by_decision_key(
        self,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one(
                {
                    "user_id": user_id,
                    "decision_idempotency_key": idempotency_key,
                },
                {"_id": 0},
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write decision lookup is temporarily unavailable"
            ) from exc

    async def decide(
        self,
        *,
        command_id: str,
        user_id: str,
        expected_status: str,
        target_status: str,
        decision: str,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
        result: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        update: dict[str, Any] = {
            "$set": {
                "status": target_status,
                "decision": decision,
                "decision_idempotency_key": idempotency_key,
                "decision_request_hash": request_hash,
                "decided_at": now,
                "updated_at": now,
            },
            "$inc": {"version": 1},
        }
        if result is not None:
            update["$set"]["result"] = result
            update["$set"]["finished_at"] = now
        if target_status == WriteCommandStatus.APPROVED.value:
            update["$set"]["next_attempt_at"] = now
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "status": expected_status,
                    "expires_at": {"$gt": now},
                },
                update,
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return None
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write decision is temporarily unavailable"
            ) from exc

    async def mark_expired(
        self,
        *,
        command_id: str,
        user_id: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "status": WriteCommandStatus.AWAITING_CONFIRMATION.value,
                    "expires_at": {"$lte": now},
                },
                {
                    "$set": {
                        "status": WriteCommandStatus.EXPIRED.value,
                        "result": {
                            "ok": False,
                            "code": "COMMAND_EXPIRED",
                            "message": "待确认操作已过期",
                        },
                        "updated_at": now,
                        "finished_at": now,
                    },
                    "$inc": {"version": 1},
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command expiration is temporarily unavailable"
            ) from exc

    async def claim_execution(
        self,
        *,
        command_id: str,
        user_id: str,
        execution_token: str,
        now: datetime,
        lease_until: datetime,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "$or": [
                        {
                            "status": {
                                "$in": [
                                    WriteCommandStatus.APPROVED.value,
                                    WriteCommandStatus.RETRY_PENDING.value,
                                ]
                            },
                            "next_attempt_at": {"$lte": now},
                        },
                        {
                            "status": WriteCommandStatus.EXECUTING.value,
                            "lease_until": {"$lte": now},
                        },
                    ],
                },
                {
                    "$set": {
                        "status": WriteCommandStatus.EXECUTING.value,
                        "execution_token": execution_token,
                        "lease_until": lease_until,
                        "started_at": now,
                        "updated_at": now,
                    },
                    "$inc": {"version": 1, "attempt_count": 1},
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command claim is temporarily unavailable"
            ) from exc

    async def find_recoverable(
        self,
        *,
        now: datetime,
        approved_before: datetime,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        try:
            documents = await self.collection.find(
                {
                    "$or": [
                        {
                            "status": {
                                "$in": [
                                    WriteCommandStatus.APPROVED.value,
                                    WriteCommandStatus.RETRY_PENDING.value,
                                ]
                            },
                            "next_attempt_at": {"$lte": now},
                            "updated_at": {"$lte": approved_before},
                        },
                        {
                            "status": WriteCommandStatus.EXECUTING.value,
                            "lease_until": {"$lte": now},
                        },
                    ]
                },
                {"_id": 0},
            ).sort("updated_at", 1).to_list(length=limit)
            return documents
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command recovery lookup is temporarily unavailable"
            ) from exc

    async def find_executing(
        self,
        *,
        command_id: str,
        user_id: str,
        execution_token: str,
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "status": WriteCommandStatus.EXECUTING.value,
                    "execution_token": execution_token,
                },
                {"_id": 0},
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB executing command lookup is temporarily unavailable"
            ) from exc

    async def mark_terminal(
        self,
        *,
        command_id: str,
        user_id: str,
        execution_token: str,
        status: str,
        result: dict[str, Any],
        now: datetime,
        session: AsyncClientSession,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "status": WriteCommandStatus.EXECUTING.value,
                    "execution_token": execution_token,
                },
                {
                    "$set": {
                        "status": status,
                        "result": result,
                        "error": None,
                        "lease_until": None,
                        "updated_at": now,
                        "finished_at": now,
                    },
                    "$inc": {"version": 1},
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
                session=session,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command completion is temporarily unavailable"
            ) from exc

    async def mark_failed(
        self,
        *,
        command_id: str,
        user_id: str,
        execution_token: str,
        error: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "status": WriteCommandStatus.EXECUTING.value,
                    "execution_token": execution_token,
                },
                {
                    "$set": {
                        "status": WriteCommandStatus.FAILED.value,
                        "result": {
                            "ok": False,
                            "code": error["code"],
                            "message": error["message"],
                        },
                        "error": error,
                        "lease_until": None,
                        "updated_at": now,
                        "finished_at": now,
                    },
                    "$inc": {"version": 1},
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB write command failure recording is temporarily unavailable"
            ) from exc

    async def mark_graph_resuming(
        self,
        *,
        command_id: str,
        user_id: str,
        resume_token: str,
        now: datetime,
        lease_until: datetime,
    ) -> dict[str, Any] | None:
        try:
            return await self.collection.find_one_and_update(
                {
                    "command_id": command_id,
                    "user_id": user_id,
                    "$or": [
                        {"graph_resume_status": "pending"},
                        {
                            "graph_resume_status": "resuming",
                            "graph_resume_lease_until": {"$lte": now},
                        },
                    ],
                },
                {
                    "$set": {
                        "graph_resume_status": "resuming",
                        "graph_resume_token": resume_token,
                        "graph_resume_lease_until": lease_until,
                        "updated_at": now,
                    }
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB graph resume claim is temporarily unavailable"
            ) from exc

    async def mark_graph_completed(
        self,
        *,
        command_id: str,
        user_id: str,
        response_text: str,
        assistant_message_id: str | None,
        now: datetime,
        resume_token: str | None = None,
    ) -> dict[str, Any] | None:
        filters: dict[str, Any] = {
            "command_id": command_id,
            "user_id": user_id,
        }
        if resume_token is not None:
            filters.update(
                {
                    "graph_resume_status": "resuming",
                    "graph_resume_token": resume_token,
                }
            )
        try:
            return await self.collection.find_one_and_update(
                filters,
                {
                    "$set": {
                        "graph_resume_status": "completed",
                        "graph_resume_lease_until": None,
                        "assistant_response": response_text,
                        "assistant_message_id": assistant_message_id,
                        "updated_at": now,
                    }
                },
                projection={"_id": 0},
                return_document=ReturnDocument.AFTER,
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB graph resume completion is temporarily unavailable"
            ) from exc
