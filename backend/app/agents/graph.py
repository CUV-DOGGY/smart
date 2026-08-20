from __future__ import annotations

import json
import logging
import uuid
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.runtime import AgentRuntimeContext
from app.agents.state import AgentState
from app.prompts.service_agent import prompt_with_task
from app.tools.service_tools import ServiceToolRegistry, ToolValidationFailure


logger = logging.getLogger(__name__)


CANCEL_PHRASES = {"算了", "不用了", "取消", "取消操作", "不操作了"}
FIELD_QUESTIONS = {
    "shop_id": "请提供店铺，或者先让我列出当前可用店铺。",
    "address_id": "请提供收货地址，或者先让我列出你的地址。",
    "order_id": "请提供需要查询或操作的订单号。",
    "items": "请提供要购买的商品和数量，例如“商品A两份”。",
}


async def model_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    latest_human = next(
        (message for message in reversed(state.get("messages", [])) if isinstance(message, HumanMessage)),
        None,
    )
    if (
        state.get("active_tool")
        and latest_human
        and str(latest_human.content).strip() in CANCEL_PHRASES
    ):
        return {
            "messages": [AIMessage(content="好的，已取消当前操作，没有执行任何业务变更。")],
            "active_tool": None,
            "active_call": None,
            "slots": {},
            "missing_slots": [],
            "pending_action": None,
        }

    model = runtime.context.llm.bind_tools(ServiceToolRegistry.definitions())
    system = SystemMessage(
        content=prompt_with_task(state.get("active_tool"), state.get("slots", {}))
    )
    messages = [system, *state.get("messages", [])[-30:]]
    response = await model.ainvoke(messages)
    return {"messages": [response]}


def route_after_model(state: AgentState) -> Literal["validate_tool", "__end__"]:
    last = state.get("messages", [])[-1]
    return "validate_tool" if isinstance(last, AIMessage) and last.tool_calls else END


async def validate_tool_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    last = state.get("messages", [])[-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {}
    call = last.tool_calls[0]
    name = call.get("name", "")
    previous_slots = state.get("slots", {}) if state.get("active_tool") == name else {}
    supplied = call.get("args") if isinstance(call.get("args"), dict) else {}
    merged = {**previous_slots, **{key: value for key, value in supplied.items() if value not in (None, "", [])}}
    extra_messages = [
        ToolMessage(
            content=json.dumps({"ok": False, "code": "ONE_TOOL_AT_A_TIME"}),
            tool_call_id=extra.get("id", "unknown"),
        )
        for extra in last.tool_calls[1:]
    ]
    try:
        normalized, missing = ServiceToolRegistry.validate(name, merged)
    except ToolValidationFailure as exc:
        return {
            "messages": [
                *extra_messages,
                ToolMessage(
                    content=json.dumps({"ok": False, "code": str(exc)}),
                    tool_call_id=call.get("id", "unknown"),
                ),
            ],
            "active_tool": None,
            "active_call": None,
            "slots": {},
            "missing_slots": [],
        }
    active_call = {"id": call.get("id", str(uuid.uuid4())), "name": name, "args": normalized}
    update = {
        "messages": extra_messages,
        "active_tool": name,
        "active_call": active_call,
        "slots": normalized,
        "missing_slots": missing,
        "approval_decision": None,
    }
    if not missing and ServiceToolRegistry.is_write(name):
        try:
            confirmation = await runtime.context.tools.prepare_confirmation(
                name,
                normalized,
                user_id=runtime.context.user_id,
            )
        except Exception:
            logger.exception("Agent confirmation preview failed tool=%s", name)
            confirmation = {
                "ok": False,
                "code": "CONFIRMATION_PREVIEW_FAILED",
                "message": "暂时无法生成操作确认信息，请稍后重试",
            }
        if not confirmation.get("ok"):
            return {
                "messages": [
                    *extra_messages,
                    ToolMessage(
                        content=json.dumps(
                            confirmation,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        tool_call_id=active_call["id"],
                    ),
                ],
                "active_tool": None,
                "active_call": None,
                "slots": {},
                "missing_slots": [],
                "pending_action": None,
            }
        update["pending_action"] = {
            "action_id": str(uuid.uuid4()),
            "tool_call_id": active_call["id"],
            "name": name,
            "args": normalized,
            "summary": confirmation["summary"],
        }
        if confirmation.get("presentation"):
            update["pending_action"]["presentation"] = confirmation["presentation"]
    else:
        update["pending_action"] = None
    return update


def route_after_validation(
    state: AgentState,
) -> Literal["clarify", "confirm_write", "execute_tool", "model"]:
    if state.get("missing_slots"):
        return "clarify"
    if state.get("pending_action"):
        return "confirm_write"
    if state.get("active_call"):
        return "execute_tool"
    return "model"


def clarification_node(state: AgentState) -> dict:
    call = state["active_call"]
    missing = state.get("missing_slots", [])
    question = " ".join(FIELD_QUESTIONS.get(field, f"请补充 {field}。") for field in missing)
    return {
        "messages": [
            ToolMessage(
                content=json.dumps({"ok": False, "code": "MISSING_ARGUMENTS", "missing": missing}, ensure_ascii=False),
                tool_call_id=call["id"],
            ),
            AIMessage(content=question),
        ]
    }


def confirmation_node(state: AgentState) -> dict:
    action = state["pending_action"]
    payload = {
        "interrupt_id": action["action_id"],
        "action": action["name"],
        "summary": action["summary"],
    }
    if action.get("presentation"):
        payload["presentation"] = action["presentation"]
    response = interrupt(payload)
    decision = response.get("decision") if isinstance(response, dict) else None
    supplied_id = response.get("interrupt_id") if isinstance(response, dict) else None
    if supplied_id != action["action_id"] or decision not in {"approve", "reject"}:
        decision = "stale"
    if decision == "reject":
        return {
            "messages": [
                ToolMessage(
                    content=json.dumps({"ok": False, "code": "USER_REJECTED"}),
                    tool_call_id=action["tool_call_id"],
                ),
                AIMessage(content="已取消，本次操作没有执行。"),
            ],
            "approval_decision": "reject",
            "active_tool": None,
            "active_call": None,
            "slots": {},
            "missing_slots": [],
            "pending_action": None,
        }
    return {"approval_decision": decision}


def route_after_confirmation(state: AgentState) -> Literal["execute_tool", "__end__"]:
    return "execute_tool" if state.get("approval_decision") == "approve" else END


async def execute_tool_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    count = state.get("tool_executions", 0)
    call = state.get("active_call")
    action = state.get("pending_action")
    if not call or count >= 4:
        return {
            "messages": [AIMessage(content="本轮工具调用次数过多，请缩小问题范围后重试。")],
            "active_tool": None,
            "active_call": None,
            "slots": {},
            "missing_slots": [],
            "pending_action": None,
        }
    action_id = action["action_id"] if action else str(uuid.uuid4())
    try:
        result = await runtime.context.tools.execute(
            call["name"],
            call["args"],
            user_id=runtime.context.user_id,
            action_id=action_id,
        )
    except Exception:
        logger.exception("Agent tool execution failed tool=%s", call["name"])
        result = {
            "ok": False,
            "code": "TOOL_EXECUTION_FAILED",
            "message": "业务服务暂时不可用，请稍后重试",
        }
    return {
        "messages": [
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                tool_call_id=call["id"],
            )
        ],
        "active_tool": None,
        "active_call": None,
        "slots": {},
        "missing_slots": [],
        "pending_action": None,
        "approval_decision": None,
        "tool_executions": count + 1,
    }


def build_service_agent(checkpointer):
    builder = StateGraph(AgentState, context_schema=AgentRuntimeContext)
    builder.add_node("model", model_node)
    builder.add_node("validate_tool", validate_tool_node)
    builder.add_node("clarify", clarification_node)
    builder.add_node("confirm_write", confirmation_node)
    builder.add_node("execute_tool", execute_tool_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route_after_model)
    builder.add_conditional_edges("validate_tool", route_after_validation)
    builder.add_edge("clarify", END)
    builder.add_conditional_edges("confirm_write", route_after_confirmation)
    builder.add_edge("execute_tool", "model")
    return builder.compile(checkpointer=checkpointer)
