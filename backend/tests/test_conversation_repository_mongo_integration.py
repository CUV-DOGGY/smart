import os
import unittest

from motor.motor_asyncio import AsyncIOMotorClient

from app.repositories.conversation_repository import ConversationRepository


RUN_INTEGRATION = os.getenv("RUN_MONGO_INTEGRATION") == "1"


@unittest.skipUnless(RUN_INTEGRATION, "set RUN_MONGO_INTEGRATION=1 to run real MongoDB tests")
class ConversationRepositoryMongoIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database_name = os.environ["TEST_MONGODB_DB_NAME"]
        if not database_name.endswith("_test"):
            self.fail("integration database name must end with _test")
        self.client = AsyncIOMotorClient(os.environ["TEST_MONGODB_URL"])
        self.database = self.client[database_name]
        self.repository = ConversationRepository(self.database)
        await self.repository.ensure_indexes()
        await self.database.conversations.delete_many({"user_id": {"$in": ["chat-user-a", "chat-user-b"]}})
        await self.database.conversation_messages.delete_many({"user_id": {"$in": ["chat-user-a", "chat-user-b"]}})

    async def asyncTearDown(self):
        await self.database.conversations.delete_many({"user_id": {"$in": ["chat-user-a", "chat-user-b"]}})
        await self.database.conversation_messages.delete_many({"user_id": {"$in": ["chat-user-a", "chat-user-b"]}})
        self.client.close()

    async def test_conversation_is_isolated_listed_and_deleted(self):
        conversation_id = await self.repository.create_conversation("chat-user-a", "测试会话")
        await self.repository.append_message(
            conversation_id=conversation_id,
            user_id="chat-user-a",
            role="user",
            content="你好",
        )
        await self.repository.append_message(
            conversation_id=conversation_id,
            user_id="chat-user-a",
            role="assistant",
            content="您好",
        )

        self.assertTrue(await self.repository.is_owned_by(conversation_id, "chat-user-a"))
        self.assertFalse(await self.repository.is_owned_by(conversation_id, "chat-user-b"))
        items, cursor = await self.repository.list_conversations("chat-user-a", limit=10, cursor=None)
        self.assertEqual(items[0]["conversation_id"], conversation_id)
        self.assertIsNone(cursor)
        messages = await self.repository.recent_messages(conversation_id, "chat-user-a", 20)
        self.assertEqual([item["content"] for item in messages], ["你好", "您好"])
        self.assertTrue(await self.repository.delete_conversation(conversation_id, "chat-user-a"))
        self.assertFalse(await self.repository.is_owned_by(conversation_id, "chat-user-a"))


if __name__ == "__main__":
    unittest.main()
