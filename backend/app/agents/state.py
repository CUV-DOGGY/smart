from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    active_tool: str | None
    active_call: dict[str, Any] | None
    slots: dict[str, Any]
    missing_slots: list[str]
    pending_action: dict[str, Any] | None
    approval_decision: str | None
    tool_executions: int
