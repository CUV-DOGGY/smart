import hashlib
import uuid
from contextlib import asynccontextmanager


class ConversationBusyError(RuntimeError):
    pass


class ConversationRunLock:
    def __init__(self, redis, *, lease_seconds: int = 120) -> None:
        self.redis = redis
        self.lease_seconds = lease_seconds

    @asynccontextmanager
    async def acquire(self, user_id: str, conversation_id: str):
        digest = hashlib.sha256(f"{user_id}:{conversation_id}".encode()).hexdigest()
        key = f"agent:conversation-lock:{digest}"
        token = str(uuid.uuid4())
        acquired = await self.redis.set(
            key,
            token,
            ex=self.lease_seconds,
            nx=True,
        )
        if not acquired:
            raise ConversationBusyError
        try:
            yield
        finally:
            await self.redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
