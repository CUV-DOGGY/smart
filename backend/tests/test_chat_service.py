import unittest
from types import SimpleNamespace

from app.services.chat_service import ChatService, ConversationNotFoundError


class FakeRepository:
    def __init__(self, owned=True):
        self.owned = owned
        self.messages = []

    async def create_conversation(self, user_id, title):
        self.created = (user_id, title)
        return "conversation-001"

    async def is_owned_by(self, conversation_id, user_id):
        self.lookup = (conversation_id, user_id)
        return self.owned

    async def append_message(self, **message):
        self.messages.append(message)
        return f"message-{len(self.messages)}"

    async def recent_messages(self, conversation_id, user_id, limit):
        return [
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in self.messages[-limit:]
        ]


class FakeLlm:
    async def astream(self, messages):
        self.messages = messages
        for text in ("你", "好"):
            yield SimpleNamespace(content=text)


class FailingLlm:
    async def astream(self, messages):
        if False:
            yield None
        raise RuntimeError("https://secret-model-host")


async def connected():
    return False


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_conversation_streams_and_persists_complete_reply(self):
        repository = FakeRepository()
        llm = FakeLlm()
        service = ChatService(repository, llm)

        conversation_id, history = await service.prepare(
            user_id="user-001",
            message="配送要多久？",
            conversation_id=None,
        )
        events = [
            event
            async for event in service.stream_reply(
                conversation_id=conversation_id,
                user_id="user-001",
                history=history,
                is_disconnected=connected,
            )
        ]

        self.assertEqual(conversation_id, "conversation-001")
        self.assertEqual([event["type"] for event in events], ["token", "token", "done"])
        self.assertEqual(repository.messages[-1]["content"], "你好")
        self.assertEqual(repository.messages[-1]["role"], "assistant")
        self.assertEqual(llm.messages[-1], ("user", "配送要多久？"))

    async def test_cannot_append_to_another_users_conversation(self):
        service = ChatService(FakeRepository(owned=False), FakeLlm())

        with self.assertRaises(ConversationNotFoundError):
            await service.prepare(
                user_id="attacker",
                message="test",
                conversation_id="owned-by-someone-else",
            )

    async def test_model_failure_is_safe_and_does_not_persist_partial_reply(self):
        repository = FakeRepository()
        service = ChatService(repository, FailingLlm())
        conversation_id, history = await service.prepare(
            user_id="user-001",
            message="hello",
            conversation_id=None,
        )

        with self.assertLogs("app.services.chat_service", level="ERROR"):
            events = [
                event
                async for event in service.stream_reply(
                    conversation_id=conversation_id,
                    user_id="user-001",
                    history=history,
                    is_disconnected=connected,
                )
            ]

        self.assertEqual(events[0]["type"], "error")
        self.assertNotIn("secret-model-host", str(events))
        self.assertEqual(len(repository.messages), 1)


if __name__ == "__main__":
    unittest.main()
