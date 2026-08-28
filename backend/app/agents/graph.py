from __future__ import annotations

import json
import logging
import uuid
from datetime import timezone
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.runtime import AgentRuntimeContext
from app.agents.state import AgentState
from app.config import settings
from app.observability import agent as agent_observability
from app.prompts.service_agent import prompt_with_task
from app.services.write_command_service import WriteCommandPreparationError
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
    with agent_observability.telemetry.start_span(
        "agent.model",
        attributes={"gen_ai.request.model": settings.MODEL_NAME},
    ) as span:
        started_at = agent_observability.telemetry.now()
        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            agent_observability.telemetry.record_exception(span, exc)
            agent_observability.telemetry.record_llm_call(
                agent_observability.telemetry.elapsed(started_at),
                model=settings.MODEL_NAME,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            raise
        agent_observability.telemetry.set_outcome(span, "completed")
        input_tokens, output_tokens = _response_token_usage(response)
        agent_observability.telemetry.record_llm_call(
            agent_observability.telemetry.elapsed(started_at),
            model=settings.MODEL_NAME,
            outcome="succeeded",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    return {"messages": [response]}


def _response_token_usage(response: AIMessage) -> tuple[int | None, int | None]:
    usage = response.usage_metadata
    if not isinstance(usage, dict):
        token_usage = response.response_metadata.get("token_usage")
        usage = token_usage if isinstance(token_usage, dict) else {}

    def token_value(*names: str) -> int | None:
        for name in names:
            value = usage.get(name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            ):
                return value
        return None

    return (
        token_value("input_tokens", "prompt_tokens"),
        token_value("output_tokens", "completion_tokens"),
    )


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
        update["pending_action"] = {
            "command_id": str(uuid.uuid4()),
            "tool_call_id": active_call["id"],
            "name": name,
            "args": normalized,
        }
    else:
        update["pending_action"] = None
    return update


def route_after_validation(
    state: AgentState,
) -> Literal["clarify", "prepare_write_command", "execute_read_tool", "model"]:
    if state.get("missing_slots"):
        return "clarify"
    if state.get("pending_action"):
        return "prepare_write_command"
    if state.get("active_call"):
        return "execute_read_tool"
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


async def prepare_write_command_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    action = state["pending_action"]
    call = state["active_call"]
    outcome = "prepared"
    error_type = None
    try:
        with agent_observability.telemetry.start_span(
            "agent.confirmation.prepare",
            attributes={
                "agent.action": action["name"],
                "app.command_id": action["command_id"],
            },
        ) as span:
            try:
                if runtime.context.command_service is None:
                    raise RuntimeError("Write command service is not configured")
                command = await runtime.context.command_service.prepare(
                    command_id=action["command_id"],
                    user_id=runtime.context.user_id,
                    conversation_id=runtime.context.conversation_id,
                    action=action["name"],
                    arguments=action["args"],
                )
            except WriteCommandPreparationError as exc:
                outcome = "failed"
                error_type = exc.code
                agent_observability.telemetry.set_outcome(
                    span,
                    outcome,
                    error_type=error_type,
                )
                raise
            except Exception as exc:
                outcome = "failed"
                error_type = type(exc).__name__
                agent_observability.telemetry.record_exception(span, exc)
                raise
            agent_observability.telemetry.set_outcome(span, outcome)
    except WriteCommandPreparationError as exc:
        result = exc.result
    except Exception:
        logger.exception("Write command preparation failed action=%s", action["name"])
        result = {
            "ok": False,
            "code": "WRITE_COMMAND_PREPARATION_FAILED",
            "message": "暂时无法生成操作确认信息，请稍后重试",
        }
    else:
        expires_at = command["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        pending_action = {
            "command_id": command["command_id"],
            "tool_call_id": action["tool_call_id"],
            "name": command["action"],
            "request_hash": command["request_hash"],
            "summary": command["summary"],
            "status": command["status"],
            "expires_at": expires_at.isoformat(),
        }
        if command.get("presentation"):
            pending_action["presentation"] = command["presentation"]
        return {"pending_action": pending_action}
    finally:
        agent_observability.telemetry.record_confirmation(
            action=action["name"],
            outcome=outcome,
            error_type=error_type,
        )

    return {
        "messages": [
            ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                tool_call_id=call["id"],
            )
        ],
        "active_tool": None,
        "active_call": None,
        "slots": {},
        "missing_slots": [],
        "pending_action": None,
    }


def route_after_write_preparation(
    state: AgentState,
) -> Literal["confirm_write", "model"]:
    return "confirm_write" if state.get("pending_action") else "model"


def confirmation_node(state: AgentState) -> dict:
    action = state["pending_action"]
    payload = {
        "interrupt_id": action["command_id"],
        "command_id": action["command_id"],
        "action": action["name"],
        "summary": action["summary"],
        "status": action["status"],
        "expires_at": action["expires_at"],
    }
    if action.get("presentation"):
        payload["presentation"] = action["presentation"]
    response = interrupt(payload)
    decision = response.get("decision") if isinstance(response, dict) else None
    supplied_id = response.get("interrupt_id") if isinstance(response, dict) else None
    if supplied_id != action["command_id"] or decision not in {"approve", "reject"}:
        decision = "stale"
    return {"approval_decision": decision}


def route_after_confirmation(
    state: AgentState,
) -> Literal["append_write_result", "__end__"]:
    return (
        "append_write_result"
        if state.get("approval_decision") in {"approve", "reject"}
        else END
    )


async def execute_read_tool_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    count = state.get("tool_executions", 0)
    call = state.get("active_call")
    if not call or count >= 4:
        return {
            "messages": [AIMessage(content="本轮工具调用次数过多，请缩小问题范围后重试。")],
            "active_tool": None,
            "active_call": None,
            "slots": {},
            "missing_slots": [],
            "pending_action": None,
        }
    if ServiceToolRegistry.is_write(call["name"]):
        raise RuntimeError("Write tools cannot execute inside LangGraph")
    started_at = agent_observability.telemetry.now()
    outcome = "succeeded"
    error_type = None
    try:
        with agent_observability.telemetry.start_span(
            f"agent.tool.{call['name']}",
            attributes={"agent.tool.name": call["name"]},
        ) as span:
            try:
                result = await runtime.context.tools.execute_read(
                    call["name"],
                    call["args"],
                    user_id=runtime.context.user_id,
                )
            except Exception as exc:
                outcome = "failed"
                error_type = type(exc).__name__
                agent_observability.telemetry.record_exception(span, exc)
                raise
            if not result.get("ok"):
                outcome = "failed"
                error_type = str(result.get("code") or "TOOL_FAILED")
            agent_observability.telemetry.set_outcome(
                span,
                outcome,
                error_type=error_type,
            )
    except Exception:
        logger.exception("Agent tool execution failed tool=%s", call["name"])
        result = {
            "ok": False,
            "code": "TOOL_EXECUTION_FAILED",
            "message": "业务服务暂时不可用，请稍后重试",
        }
    finally:
        agent_observability.telemetry.record_tool_call(
            agent_observability.telemetry.elapsed(started_at),
            tool_name=call["name"],
            outcome=outcome,
            error_type=error_type,
        )
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


async def append_write_result_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict:
    count = state.get("tool_executions", 0)
    action = state.get("pending_action")
    if not action:
        return {
            "messages": [AIMessage(content="写操作结果丢失，请重新发起操作。")],
            "approval_decision": None,
        }
    try:
        command = await runtime.context.command_service.get_owned(
            command_id=action["command_id"],
            user_id=runtime.context.user_id,
        )
        result = runtime.context.command_service.result_for_agent(command)
    except Exception:
        logger.exception(
            "Write command result lookup failed command_id=%s",
            action["command_id"],
        )
        result = {
            "ok": False,
            "code": "WRITE_COMMAND_RESULT_UNAVAILABLE",
            "message": "暂时无法读取写操作结果，请稍后重试",
        }
    return {
        "messages": [
            ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                tool_call_id=action["tool_call_id"],
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
    builder.add_node("prepare_write_command", prepare_write_command_node)
    builder.add_node("confirm_write", confirmation_node)
    builder.add_node("execute_read_tool", execute_read_tool_node)
    builder.add_node("append_write_result", append_write_result_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route_after_model)
    builder.add_conditional_edges("validate_tool", route_after_validation)
    builder.add_edge("clarify", END)
    builder.add_conditional_edges(
        "prepare_write_command",
        route_after_write_preparation,
    )
    builder.add_conditional_edges("confirm_write", route_after_confirmation)
    builder.add_edge("execute_read_tool", "model")
    builder.add_edge("append_write_result", "model")
    return builder.compile(checkpointer=checkpointer)
