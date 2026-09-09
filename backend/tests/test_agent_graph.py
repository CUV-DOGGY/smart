import unittest
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
        self.confirmation_calls = []

    async def prepare_confirmation(self, name, arguments, *, user_id):
        self.confirmation_calls.append((name, arguments, user_id))
        result = {"ok": True, "summary": f"确认执行 {name}"}
        if name == "create_order":
            result["presentation"] = {
                "kind": "order",
                "shop_id": arguments["shop_id"],
                "shop_name": "测试店铺",
                "address_id": arguments["address_id"],
                "receiver_name": "测试用户",
                "receiver_phone": "138****8000",
                "delivery_address": "北京市朝阳区测试路1号",
                "items": [{
                    "food_id": "food-001",
                    "food_name": "测试商品",
                    "quantity": 2,
                    "unit_price": 12.5,
                    "line_total": 25.0,
                }],
                "goods_amount": 25.0,
                "delivery_fee": 5.0,
                "total_price": 30.0,
                "currency": "CNY",
            }
        if name == "cancel_order":
            result["presentation"] = {
                "kind": "order_cancellation",
                "order_id": arguments["order_id"],
                "shop_id": "shop-001",
                "shop_name": "测试店铺",
                "items": [{
                    "food_id": "food-001",
                    "food_name": "测试商品",
                    "quantity": 2,
                    "unit_price": 12.5,
                    "line_total": 25.0,
                }],
                "current_status": "preparing",
                "create_time": "2026-08-26T12:00:00Z",
                "total_price": 30.0,
                "currency": "CNY",
            }
        return result

    async def execute(self, name, arguments, *, user_id, action_id):
        self.calls.append((name, arguments, user_id, action_id))
        return {"ok": True, "result": "done"}

    async def execute_read(self, name, arguments, *, user_id):
        return await self.execute(
            name,
            arguments,
            user_id=user_id,
            action_id="read-only",
        )


class FailingRegistry(FakeRegistry):
    async def execute(self, name, arguments, *, user_id, action_id):
        self.calls.append((name, arguments, user_id, action_id))
        raise RuntimeError("database document validation failed")

    async def execute_read(self, name, arguments, *, user_id):
        return await self.execute(
            name,
            arguments,
            user_id=user_id,
            action_id="read-only",
        )


class FakeCommandService:
    def __init__(self, registry):
        self.registry = registry
        self.commands = {}

    async def prepare(
        self,
        *,
        command_id,
        user_id,
        conversation_id,
        action,
        arguments,
    ):
        confirmation = await self.registry.prepare_confirmation(
            action,
            arguments,
            user_id=user_id,
        )
        command = {
            "command_id": command_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "action": action,
            "arguments": arguments,
            "request_hash": f"hash:{command_id}",
            "status": "awaiting_confirmation",
            "version": 1,
            "summary": confirmation["summary"],
            "presentation": confirmation.get("presentation"),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
            "result": None,
        }
        self.commands[command_id] = command
        return command

    async def get_owned(self, *, command_id, user_id):
        command = self.commands[command_id]
        if command["user_id"] != user_id:
            raise RuntimeError("not owned")
        return command

    @staticmethod
    def result_for_agent(command):
        if not command.get("result"):
            raise RuntimeError("not terminal")
        return command["result"]

    def finish(self, command_id, *, status, result):
        self.commands[command_id]["status"] = status
        self.commands[command_id]["result"] = result


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
        command_service = FakeCommandService(registry)
        context = AgentRuntimeContext(
            "user-001",
            FakeModel(responses),
            registry,
            command_service,
            "conversation-001",
        )
        config = {"configurable": {"thread_id": "user-001:conversation-001"}}
        return graph, registry, command_service, context, config

    async def test_read_tool_executes_without_confirmation(self):
        graph, registry, _, context, config = self.make(
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
        graph, registry, _, context, config = self.make(
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
        graph, registry, commands, context, config = self.make(
            [tool_call("cancel_order", {"order_id": "order-001"}), AIMessage(content="已提交取消申请。")]
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="取消 order-001")]}, config=config, context=context
        )
        snapshot = await graph.aget_state(config)
        self.assertEqual(registry.calls, [])
        payload = snapshot.tasks[0].interrupts[0].value
        self.assertEqual(
            payload["presentation"]["kind"],
            "order_cancellation",
        )
        self.assertEqual(payload["presentation"]["order_id"], "order-001")
        commands.finish(
            payload["command_id"],
            status="succeeded",
            result={"ok": True, "order_status": "canceling"},
        )
        result = await graph.ainvoke(
            Command(resume={"interrupt_id": payload["interrupt_id"], "decision": "approve"}),
            config=config,
            context=context,
        )
        self.assertEqual(registry.calls, [])
        self.assertEqual(result["messages"][-1].content, "已提交取消申请。")

    async def test_create_order_interrupt_contains_structured_preview(self):
        graph, registry, _, context, config = self.make([
            tool_call(
                "create_order",
                {
                    "shop_id": "shop-001",
                    "address_id": "address-001",
                    "items": [{"food_id": "food-001", "quantity": 2}],
                },
            )
        ])

        await graph.ainvoke(
            {"messages": [HumanMessage(content="帮我下单")]},
            config=config,
            context=context,
        )

        snapshot = await graph.aget_state(config)
        payload = snapshot.tasks[0].interrupts[0].value
        self.assertEqual(payload["presentation"]["kind"], "order")
        self.assertEqual(payload["presentation"]["total_price"], 30.0)
        self.assertEqual(registry.calls, [])
        self.assertEqual(registry.confirmation_calls[0][2], "user-001")

    async def test_reject_never_calls_write_service(self):
        graph, registry, commands, context, config = self.make(
            [
                tool_call("delete_address", {"address_id": "address-001"}),
                AIMessage(content="已取消，本次操作没有执行。"),
            ]
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="删除地址")]}, config=config, context=context
        )
        snapshot = await graph.aget_state(config)
        payload = snapshot.tasks[0].interrupts[0].value
        commands.finish(
            payload["command_id"],
            status="rejected",
            result={
                "ok": False,
                "code": "USER_REJECTED",
                "message": "用户取消了本次操作",
            },
        )
        result = await graph.ainvoke(
            Command(resume={"interrupt_id": payload["interrupt_id"], "decision": "reject"}),
            config=config,
            context=context,
        )
        self.assertEqual(registry.calls, [])
        self.assertEqual(result["messages"][-1].content, "已取消，本次操作没有执行。")

    async def test_tool_failure_is_returned_as_a_paired_tool_message(self):
        checkpointer = InMemorySaver()
        graph = build_service_agent(checkpointer)
        registry = FailingRegistry()
        model = FakeModel(
            [
                tool_call("list_products", {"shop_id": "shop-001"}),
                AIMessage(content="商品服务暂时不可用，请稍后重试。"),
            ]
        )
        context = AgentRuntimeContext(
            "user-001",
            model,
            registry,
            FakeCommandService(registry),
            "tool-failure",
        )
        config = {"configurable": {"thread_id": "user-001:tool-failure"}}

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="查一下商品")]},
            config=config,
            context=context,
        )

        tool_result = next(
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        )
        self.assertEqual(tool_result.tool_call_id, "call-1")
        self.assertIn("TOOL_EXECUTION_FAILED", tool_result.content)
        self.assertEqual(
            result["messages"][-1].content,
            "商品服务暂时不可用，请稍后重试。",
        )


if __name__ == "__main__":
    unittest.main()
