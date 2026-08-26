from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.types import Command

from app.agents.runtime import AgentRuntimeContext


logger = logging.getLogger(__name__)


class AgentConfirmationRequiredError(RuntimeError):
    pass


class AgentConfirmationStaleError(RuntimeError):
    pass


class AgentRunner:
    def __init__(self, graph, checkpointer) -> None:
        self.graph = graph
        self.checkpointer = checkpointer

    @staticmethod
    def thread_id(user_id: str, conversation_id: str) -> str:
        return f"{user_id}:{conversation_id}"

    def config(self, user_id: str, conversation_id: str) -> dict:
        return {
            "configurable": {"thread_id": self.thread_id(user_id, conversation_id)},
            "recursion_limit": 12,
        }

    async def pending_confirmation(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        snapshot = await self.graph.aget_state(self.config(user_id, conversation_id))
        for task in getattr(snapshot, "tasks", ()):
            for item in getattr(task, "interrupts", ()):
                value = getattr(item, "value", None)
                if isinstance(value, dict) and value.get("interrupt_id"):
                    return value
        return None

    async def stream_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        history: list[dict],
        context: AgentRuntimeContext,
    ) -> AsyncIterator[dict[str, Any]]:
        if await self.pending_confirmation(user_id, conversation_id):
            raise AgentConfirmationRequiredError
        config = self.config(user_id, conversation_id)
        snapshot = await self.graph.aget_state(config)
        snapshot_values = getattr(snapshot, "values", None)
        if snapshot_values and self._has_unanswered_tool_calls(
            snapshot_values.get("messages", [])
        ):
            logger.warning(
                "Resetting invalid agent checkpoint conversation_id=%s",
                conversation_id,
            )
            await self.delete_thread(user_id, conversation_id)
            snapshot_values = None
        if snapshot_values:
            input_messages = [HumanMessage(content=message)]
        else:
            input_messages = [
                HumanMessage(content=item["content"])
                if item.get("role") == "user"
                else AIMessage(content=item["content"])
                for item in history
                if item.get("role") in {"user", "assistant"}
            ]
        async for event in self._stream_graph(
            {"messages": input_messages, "tool_executions": 0},
            config=config,
            context=context,
        ):
            yield event

    async def stream_resume(
        self,
        *,
        user_id: str,
        conversation_id: str,
        interrupt_id: str,
        decision: str,
        context: AgentRuntimeContext,
    ) -> AsyncIterator[dict[str, Any]]:
        pending = await self.pending_confirmation(user_id, conversation_id)
        if pending is None or pending.get("interrupt_id") != interrupt_id:
            raise AgentConfirmationStaleError
        command = Command(
            resume={"interrupt_id": interrupt_id, "decision": decision}
        )
        async for event in self._stream_graph(
            command,
            config=self.config(user_id, conversation_id),
            context=context,
        ):
            yield event

    async def _stream_graph(
        self,
        graph_input,
        *,
        config: dict,
        context: AgentRuntimeContext,
    ) -> AsyncIterator[dict[str, Any]]:
        emitted = ""
        yield {"type": "status", "phase": "thinking", "label": "正在理解问题"}
        async for part in self.graph.astream(
            graph_input,
            config=config,
            context=context,
            stream_mode=["messages", "updates"],
            version="v2",
        ):
            part_type, data = self._part(part)
            if part_type == "messages":
                message, metadata = data
                node = metadata.get("langgraph_node", "") if isinstance(metadata, dict) else ""
                if node not in {"model", "clarify", "confirm_write"}:
                    continue
                text = self._message_text(message)
                if text:
                    emitted += text
                    yield {"type": "token", "delta": text}
            elif part_type == "updates" and isinstance(data, dict):
                if "execute_read_tool" in data:
                    yield {"type": "status", "phase": "using_tool", "label": "正在调用业务服务"}
                elif "append_write_result" in data:
                    yield {"type": "status", "phase": "reading_result", "label": "正在整理执行结果"}

        pending = await self._pending_from_config(config)
        if pending:
            yield {"type": "confirmation_required", **pending}
            return
        if not emitted:
            snapshot = await self.graph.aget_state(config)
            messages = snapshot.values.get("messages", []) if snapshot.values else []
            if messages and isinstance(messages[-1], AIMessage):
                text = self._message_text(messages[-1])
                if text:
                    yield {"type": "token", "delta": text}

    async def _pending_from_config(self, config: dict) -> dict | None:
        thread_id = config["configurable"]["thread_id"]
        user_id, conversation_id = thread_id.split(":", 1)
        return await self.pending_confirmation(user_id, conversation_id)

    @staticmethod
    def _part(part) -> tuple[str | None, Any]:
        if isinstance(part, dict) and "type" in part:
            return part.get("type"), part.get("data")
        if isinstance(part, tuple) and len(part) == 2:
            return part
        return None, None

    @staticmethod
    def _message_text(message: Any) -> str:
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return ""
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            )
        return ""

    @staticmethod
    def _has_unanswered_tool_calls(messages: list[Any]) -> bool:
        for index, message in enumerate(messages):
            if not isinstance(message, AIMessage) or not message.tool_calls:
                continue
            unanswered = {
                call.get("id")
                for call in message.tool_calls
                if isinstance(call, dict) and call.get("id")
            }
            following_index = index + 1
            while (
                following_index < len(messages)
                and isinstance(messages[following_index], ToolMessage)
            ):
                unanswered.discard(messages[following_index].tool_call_id)
                following_index += 1
            if unanswered:
                return True
        return False

    async def delete_thread(self, user_id: str, conversation_id: str) -> None:
        await self.checkpointer.adelete_thread(self.thread_id(user_id, conversation_id))
