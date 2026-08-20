import unittest

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.graph import build_service_agent
from app.agents.runtime import AgentRuntimeContext


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

    async def execute(self, name, arguments, *, user_id, action_id):
        self.calls.append((name, arguments, user_id, action_id))
        return {"ok": True, "result": "done"}


def tool_call(name, args, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
    def make(self, responses):
        checkpointer = InMemorySaver()
        graph = build_service_agent(checkpointer)
        registry = FakeRegistry()
        context = AgentRuntimeContext("user-001", FakeModel(responses), registry)
        config = {"configurable": {"thread_id": "user-001:conversation-001"}}
        return graph, registry, context, config

    async def test_read_tool_executes_without_confirmation(self):
        graph, registry, context, config = self.make(
            [tool_call("list_orders", {}), AIMessage(content="你目前没有订单。")]
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="查一下我的订单")]},
            config=config,
            context=context,
        )
        self.assertEqual(registry.calls[0][0], "list_orders")
        self.assertEqual(registry.calls[0][2], "user-001")
        self.assertEqual(result["messages"][-1].content, "你目前没有订单。")

    async def test_missing_slot_is_collected_on_next_turn(self):
        graph, registry, context, config = self.make(
            [
                tool_call("get_order", {}),
                tool_call("get_order", {"order_id": "order-001"}, "call-2"),
                AIMessage(content="订单正在处理中。"),
            ]
        )
        first = await graph.ainvoke(
            {"messages": [HumanMessage(content="查订单")]}, config=config, context=context
        )
        self.assertIn("订单号", first["messages"][-1].content)
        second = await graph.ainvoke(
            {"messages": [HumanMessage(content="order-001")]}, config=config, context=context
        )
        self.assertEqual(registry.calls[0][1], {"order_id": "order-001"})
        self.assertEqual(second["messages"][-1].content, "订单正在处理中。")

    async def test_write_waits_for_approval_and_executes_once(self):
        graph, registry, context, config = self.make(
            [tool_call("cancel_order", {"order_id": "order-001"}), AIMessage(content="已提交取消申请。")]
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="取消 order-001")]}, config=config, context=context
        )
        snapshot = await graph.aget_state(config)
        self.assertEqual(registry.calls, [])
        payload = snapshot.tasks[0].interrupts[0].value
        result = await graph.ainvoke(
            Command(resume={"interrupt_id": payload["interrupt_id"], "decision": "approve"}),
            config=config,
            context=context,
        )
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(result["messages"][-1].content, "已提交取消申请。")

    async def test_reject_never_calls_write_service(self):
        graph, registry, context, config = self.make(
            [tool_call("delete_address", {"address_id": "address-001"})]
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="删除地址")]}, config=config, context=context
        )
        snapshot = await graph.aget_state(config)
        payload = snapshot.tasks[0].interrupts[0].value
        result = await graph.ainvoke(
            Command(resume={"interrupt_id": payload["interrupt_id"], "decision": "reject"}),
            config=config,
            context=context,
        )
        self.assertEqual(registry.calls, [])
        self.assertEqual(result["messages"][-1].content, "已取消，本次操作没有执行。")


if __name__ == "__main__":
    unittest.main()
