import os
import unittest

from langchain_core.messages import AIMessage
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from app.agents.graph import build_service_agent
from app.agents.runner import AgentConfirmationStaleError, AgentRunner
from app.agents.runtime import AgentRuntimeContext


RUN_INTEGRATION = os.getenv("RUN_MONGO_INTEGRATION") == "1"


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, _messages):
        return self.responses.pop(0)


class FakeRegistry:
    def __init__(self):
        self.calls = []

    async def prepare_confirmation(self, name, arguments, *, user_id):
        return {"ok": True, "summary": f"确认执行 {name}"}

    async def execute(self, name, arguments, *, user_id, action_id):
        self.calls.append((name, arguments, user_id, action_id))
        return {"ok": True}


@unittest.skipUnless(RUN_INTEGRATION, "set RUN_MONGO_INTEGRATION=1 to run real MongoDB tests")
class AgentCheckpointMongoIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database_name = os.environ["TEST_MONGODB_DB_NAME"]
        if not self.database_name.endswith("_test"):
            self.fail("integration database name must end with _test")
        self.client = MongoClient(os.environ["TEST_MONGODB_URL"])
        self.thread_id = "checkpoint-user:checkpoint-conversation"
        self.saver = self.make_saver()
        await self.saver.adelete_thread(self.thread_id)

    def make_saver(self):
        return MongoDBSaver(
            self.client,
            db_name=self.database_name,
            checkpoint_collection_name="agent_checkpoints",
            writes_collection_name="agent_checkpoint_writes",
        )

    async def asyncTearDown(self):
        await self.saver.adelete_thread(self.thread_id)
        self.client.close()

    async def test_confirmation_survives_graph_rebuild_and_can_be_rejected(self):
        registry = FakeRegistry()
        initial_context = AgentRuntimeContext(
            "checkpoint-user",
            FakeModel([
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "cancel_order",
                        "args": {"order_id": "order-001"},
                        "id": "call-001",
                        "type": "tool_call",
                    }],
                )
            ]),
            registry,
        )
        runner = AgentRunner(build_service_agent(self.saver), self.saver)
        first_events = [
            event
            async for event in runner.stream_message(
                user_id="checkpoint-user",
                conversation_id="checkpoint-conversation",
                message="取消订单 order-001",
                history=[{"role": "user", "content": "取消订单 order-001"}],
                context=initial_context,
            )
        ]
        confirmation = next(
            event for event in first_events if event["type"] == "confirmation_required"
        )
        self.assertEqual(registry.calls, [])

        rebuilt_saver = self.make_saver()
        rebuilt = AgentRunner(build_service_agent(rebuilt_saver), rebuilt_saver)
        pending = await rebuilt.pending_confirmation(
            "checkpoint-user", "checkpoint-conversation"
        )
        self.assertEqual(pending["interrupt_id"], confirmation["interrupt_id"])
        self.assertIsNone(
            await rebuilt.pending_confirmation(
                "another-user", "checkpoint-conversation"
            )
        )
        resume_context = AgentRuntimeContext(
            "checkpoint-user",
            FakeModel([]),
            registry,
        )
        resumed_events = [
            event
            async for event in rebuilt.stream_resume(
                user_id="checkpoint-user",
                conversation_id="checkpoint-conversation",
                interrupt_id=confirmation["interrupt_id"],
                decision="reject",
                context=resume_context,
            )
        ]
        self.assertEqual(registry.calls, [])
        self.assertTrue(any(event["type"] == "token" for event in resumed_events))
        self.assertIsNone(
            await rebuilt.pending_confirmation(
                "checkpoint-user", "checkpoint-conversation"
            )
        )
        with self.assertRaises(AgentConfirmationStaleError):
            events = rebuilt.stream_resume(
                user_id="checkpoint-user",
                conversation_id="checkpoint-conversation",
                interrupt_id=confirmation["interrupt_id"],
                decision="reject",
                context=resume_context,
            )
            await anext(events)


if __name__ == "__main__":
    unittest.main()
