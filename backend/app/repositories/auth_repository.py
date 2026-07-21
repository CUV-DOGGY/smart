from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError


class UsernameConflictError(RuntimeError):
    """用户名唯一索引冲突。"""


class AuthRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.user_collection = db["users"]

    async def create_user(self, user_data: dict) -> None:
        try:
            await self.user_collection.insert_one(user_data)
        except DuplicateKeyError as exc:
            raise UsernameConflictError("用户名已经存在") from exc

    async def find_by_username(self, username: str) -> dict | None:
        return await self.user_collection.find_one(
            {"username": username},
            {"_id": 0},
        )

    async def find_by_user_id(self, user_id: str) -> dict | None:
        return await self.user_collection.find_one(
            {"user_id": user_id},
            {"_id": 0},
        )

    async def ensure_indexes(self) -> None:
        await self.user_collection.create_index(
            [("user_id", 1)],
            unique=True,
            name="uq_user_id",
        )
        await self.user_collection.create_index(
            [("username", 1)],
            unique=True,
            name="uq_username",
        )
