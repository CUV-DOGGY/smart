import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.runner import AgentRunner


class RecordingRunner(AgentRunner):
    async def _stream_graph(self, graph_input, *, config, context):
        self.graph_input = graph_input
        yield {"type": "done"}


class AgentRunnerCheckpointValidationTests(unittest.TestCase):
    def test_detects_tool_call_without_immediate_tool_result(self):
        messages = [
            HumanMessage(content="查询商品"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_products",
                        "args": {"shop_id": "shop-001"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            HumanMessage(content="重试"),
        ]

        self.assertTrue(AgentRunner._has_unanswered_tool_calls(messages))

    def test_accepts_tool_call_with_matching_tool_result(self):
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_products",
                        "args": {"shop_id": "shop-001"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(
                content='{"ok":true,"items":[]}',
                tool_call_id="call-1",
            ),
            AIMessage(content="暂无商品。"),
        ]

        self.assertFalse(AgentRunner._has_unanswered_tool_calls(messages))


class AgentRunnerCheckpointRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_checkpoint_is_deleted_and_visible_history_is_reused(self):
        broken_messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_products",
                        "args": {"shop_id": "shop-001"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
        graph = MagicMock()
        graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(
                values={"messages": broken_messages},
                tasks=(),
            )
        )
        checkpointer = MagicMock()
        checkpointer.adelete_thread = AsyncMock()
        runner = RecordingRunner(graph, checkpointer)

        events = [
            event
            async for event in runner.stream_message(
                user_id="user-001",
                conversation_id="conversation-001",
                message="重新查询商品",
                history=[
                    {"role": "user", "content": "我想吃肯德基"},
                    {"role": "assistant", "content": "我来查询商品。"},
                    {"role": "user", "content": "重新查询商品"},
                ],
                context=MagicMock(),
            )
        ]

        self.assertEqual(events, [{"type": "done"}])
        checkpointer.adelete_thread.assert_awaited_once_with(
            "user-001:conversation-001"
        )
        rebuilt = runner.graph_input["messages"]
        self.assertEqual(
            [message.content for message in rebuilt],
            ["我想吃肯德基", "我来查询商品。", "重新查询商品"],
        )


if __name__ == "__main__":
    unittest.main()
