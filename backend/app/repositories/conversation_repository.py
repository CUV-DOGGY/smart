import base64
import binascii
import json
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.database_errors import (
    DatabaseUnavailableError,
    MONGO_UNAVAILABLE_EXCEPTIONS,
)


class ConversationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.conversations = db["conversations"]
        self.messages = db["conversation_messages"]

    async def ensure_indexes(self) -> None:
        try:
            await self.conversations.create_index(
                [("conversation_id", 1)],
                unique=True,
                name="uq_conversation_id",
            )
            await self.conversations.create_index(
                [("user_id", 1), ("updated_at", -1), ("conversation_id", -1)],
                name="ix_user_conversation_updated",
            )
            await self.messages.create_index(
                [("conversation_id", 1), ("sequence", 1)],
                unique=True,
                name="uq_conversation_message_sequence",
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB conversation index initialization failed"
            ) from exc

    async def create_conversation(self, user_id: str, title: str) -> str:
        conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        try:
            await self.conversations.insert_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "title": title,
                    "next_sequence": 0,
                    "created_at": now,
                    "updated_at": now,
                    "deleted_at": None,
                }
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB conversation creation is temporarily unavailable"
            ) from exc
        return conversation_id

    async def is_owned_by(self, conversation_id: str, user_id: str) -> bool:
        try:
            document = await self.conversations.find_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "deleted_at": None,
                },
                {"_id": 1},
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB conversation lookup is temporarily unavailable"
            ) from exc
        return document is not None

    async def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> str | None:
        now = datetime.now(timezone.utc)
        try:
            conversation = await self.conversations.find_one_and_update(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "deleted_at": None,
                },
                {
                    "$inc": {"next_sequence": 1},
                    "$set": {"updated_at": now},
                },
                projection={"_id": 0, "next_sequence": 1},
                return_document=ReturnDocument.AFTER,
            )
            if conversation is None:
                return None
            message_id = str(uuid.uuid4())
            await self.messages.insert_one(
                {
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "role": role,
                    "content": content,
                    "sequence": conversation["next_sequence"],
                    "created_at": now,
                }
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB message persistence is temporarily unavailable"
            ) from exc
        return message_id

    async def recent_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int,
    ) -> list[dict]:
        try:
            documents = await self.messages.find(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                },
                {"_id": 0},
            ).sort("sequence", -1).to_list(length=limit)
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB message history is temporarily unavailable"
            ) from exc
        return list(reversed(documents))

    async def list_conversations(
        self,
        user_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        filters: dict = {"user_id": user_id, "deleted_at": None}
        if cursor:
            updated_at, conversation_id = self._decode_cursor(cursor)
            filters["$or"] = [
                {"updated_at": {"$lt": updated_at}},
                {
                    "updated_at": updated_at,
                    "conversation_id": {"$lt": conversation_id},
                },
            ]
        try:
            documents = await self.conversations.find(
                filters,
                {
                    "_id": 0,
                    "conversation_id": 1,
                    "title": 1,
                    "created_at": 1,
                    "updated_at": 1,
                },
            ).sort([("updated_at", -1), ("conversation_id", -1)]).to_list(
                length=limit + 1
            )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB conversation listing is temporarily unavailable"
            ) from exc
        has_more = len(documents) > limit
        items = documents[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = self._encode_cursor(
                last["updated_at"],
                last["conversation_id"],
            )
        return items, next_cursor

    async def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        try:
            result = await self.conversations.update_one(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "deleted_at": None,
                },
                {"$set": {"deleted_at": now, "updated_at": now}},
            )
            if result.modified_count:
                await self.messages.delete_many(
                    {"conversation_id": conversation_id, "user_id": user_id}
                )
        except MONGO_UNAVAILABLE_EXCEPTIONS as exc:
            raise DatabaseUnavailableError(
                "MongoDB conversation deletion is temporarily unavailable"
            ) from exc
        return result.modified_count == 1

    @staticmethod
    def _encode_cursor(updated_at: datetime, conversation_id: str) -> str:
        payload = json.dumps(
            [updated_at.isoformat(), conversation_id],
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        try:
            padding = "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(cursor + padding)
            timestamp, conversation_id = json.loads(decoded)
            updated_at = datetime.fromisoformat(timestamp)
            if updated_at.tzinfo is None or not conversation_id:
                raise ValueError
            return updated_at, str(conversation_id)
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
            raise ValueError("Invalid conversation cursor") from exc
