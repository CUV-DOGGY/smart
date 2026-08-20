import unittest

from app.integrations.conversation_lock import (
    ConversationBusyError,
    ConversationRunLock,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.keys = []

    async def set(self, key, value, *, ex, nx):
        self.keys.append((key, ex, nx))
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script, _num_keys, key, token):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0


class ConversationRunLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_conversation_is_exclusive_and_released(self):
        redis = FakeRedis()
        lock = ConversationRunLock(redis, lease_seconds=120)
        first = lock.acquire("user-001", "conversation-001")
        await first.__aenter__()
        with self.assertRaises(ConversationBusyError):
            async with lock.acquire("user-001", "conversation-001"):
                pass
        await first.__aexit__(None, None, None)
        async with lock.acquire("user-001", "conversation-001"):
            pass

        key, lease, nx = redis.keys[0]
        self.assertNotIn("user-001", key)
        self.assertNotIn("conversation-001", key)
        self.assertEqual(lease, 120)
        self.assertTrue(nx)

    async def test_token_mismatch_does_not_release_another_owner(self):
        redis = FakeRedis()
        lock = ConversationRunLock(redis)
        context = lock.acquire("user-001", "conversation-001")
        await context.__aenter__()
        key = next(iter(redis.values))
        redis.values[key] = "new-owner-token"
        await context.__aexit__(None, None, None)
        self.assertEqual(redis.values[key], "new-owner-token")


if __name__ == "__main__":
    unittest.main()
