import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from app.agents.runner import (
    AgentConfirmationRequiredError,
    AgentConfirmationStaleError,
    AgentRunner,
)
from app.agents.runtime import AgentRuntimeContext
from app.config import settings
from app.integrations.conversation_lock import ConversationRunLock
from app.observability import agent as agent_observability
from app.ports.repositories import ConversationRepositoryPort
from app.constants.write_command_status import is_terminal_write_command_status
from app.services.conversation_service import ConversationNotFoundError
from app.services.write_command_service import WriteCommandError


logger = logging.getLogger(__name__)


class AgentChatService:
    def __init__(
        self,
        repository: ConversationRepositoryPort,
        runner: AgentRunner,
        run_lock: ConversationRunLock,
        runtime_context: AgentRuntimeContext,
        command_service,
        command_executor,
        *,
        timeout_seconds: int,
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.run_lock = run_lock
        self.runtime_context = runtime_context
        self.command_service = command_service
        self.command_executor = command_executor
        self.timeout_seconds = timeout_seconds

    async def prepare_message(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: str | None,
    ) -> str:
        attributes = {}
        if conversation_id is not None:
            attributes["app.conversation_id"] = conversation_id
        with agent_observability.telemetry.start_span(
            "conversation.load",
            attributes=attributes,
        ) as span:
            try:
                if conversation_id is None:
                    created_id = await self.repository.create_conversation(
                        user_id,
                        self._title_from_message(message),
                    )
                    if span.is_recording():
                        span.set_attribute("app.conversation_id", created_id)
                    return created_id
                if not await self.repository.is_owned_by(
                    conversation_id,
                    user_id,
                ):
                    raise ConversationNotFoundError
                if await self.runner.pending_confirmation(
                    user_id,
                    conversation_id,
                ):
                    raise AgentConfirmationRequiredError
                return conversation_id
            except Exception as exc:
                agent_observability.telemetry.record_exception(span, exc)
                raise

    async def accept_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
    ) -> list[dict]:
        if await self.runner.pending_confirmation(user_id, conversation_id):
            raise AgentConfirmationRequiredError
        attributes = {"app.conversation_id": conversation_id}
        with agent_observability.telemetry.start_span(
            "conversation.persist",
            attributes=attributes,
        ) as span:
            try:
                saved = await self.repository.append_message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="user",
                    content=message,
                )
            except Exception as exc:
                agent_observability.telemetry.record_exception(span, exc)
                raise
        if saved is None:
            raise ConversationNotFoundError
        with agent_observability.telemetry.start_span(
            "conversation.load",
            attributes=attributes,
        ) as span:
            try:
                return await self.repository.recent_messages(
                    conversation_id,
                    user_id,
                    limit=30,
                )
            except Exception as exc:
                agent_observability.telemetry.record_exception(span, exc)
                raise

    async def ensure_resume(
        self,
        *,
        user_id: str,
        conversation_id: str,
        interrupt_id: str,
    ) -> dict:
        if not await self.repository.is_owned_by(conversation_id, user_id):
            raise ConversationNotFoundError
        pending = await self.runner.pending_confirmation(user_id, conversation_id)
        if pending is not None and pending.get("interrupt_id") == interrupt_id:
            return {"pending": True, "confirmation": pending}
        try:
            command = await self.command_service.get_owned(
                command_id=interrupt_id,
                user_id=user_id,
            )
        except WriteCommandError as exc:
            raise AgentConfirmationStaleError from exc
        if command.get("conversation_id") != conversation_id:
            raise AgentConfirmationStaleError
        if not is_terminal_write_command_status(command.get("status", "")):
            raise AgentConfirmationStaleError
        return {"pending": False, "command": command}

    async def stream_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
        history: list[dict],
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict]:
        source = self.runner.stream_message(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            history=history,
            context=self.runtime_context,
        )
        async for event in self._persisted_stream(
            source,
            user_id=user_id,
            conversation_id=conversation_id,
            is_disconnected=is_disconnected,
        ):
            yield event

    async def stream_resume(
        self,
        *,
        user_id: str,
        conversation_id: str,
        interrupt_id: str,
        decision: str,
        idempotency_key: str,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict]:
        confirmation_action = "unknown"
        confirmation_recorded = False
        try:
            resume_state = await self.ensure_resume(
                user_id=user_id,
                conversation_id=conversation_id,
                interrupt_id=interrupt_id,
            )
            command = await self.command_service.decide(
                command_id=interrupt_id,
                user_id=user_id,
                decision=decision,
                idempotency_key=idempotency_key,
            )
            confirmation_action = str(command.get("action") or "unknown")
            agent_observability.telemetry.record_confirmation(
                action=confirmation_action,
                outcome=decision,
            )
            confirmation_recorded = True
            if decision == "approve":
                yield {
                    "type": "status",
                    "phase": "executing_write",
                    "label": "正在执行已确认操作",
                }
                command = await self.command_executor.execute_or_replay(
                    command_id=interrupt_id,
                    user_id=user_id,
                )

            if not is_terminal_write_command_status(command["status"]):
                yield {
                    "type": "error",
                    "code": "WRITE_COMMAND_EXECUTION_PENDING",
                    "message": "写操作仍在处理中，请稍后重试",
                    "retryable": True,
                }
                return

            if not resume_state["pending"]:
                async for event in self._replay_command_response(
                    command=command,
                    user_id=user_id,
                    conversation_id=conversation_id,
                ):
                    yield event
                return

            resume_token = str(uuid.uuid4())
            resuming = await self.command_service.mark_graph_resuming(
                command_id=interrupt_id,
                user_id=user_id,
                resume_token=resume_token,
            )
            if resuming.get("graph_resume_token") != resume_token:
                yield {
                    "type": "error",
                    "code": "GRAPH_RESUME_IN_PROGRESS",
                    "message": "正在生成操作结果，请稍后重试",
                    "retryable": True,
                }
                return
            source = self.runner.stream_resume(
                user_id=user_id,
                conversation_id=conversation_id,
                interrupt_id=interrupt_id,
                decision=decision,
                context=self.runtime_context,
            )
            async for event in self._persisted_stream(
                source,
                user_id=user_id,
                conversation_id=conversation_id,
                is_disconnected=is_disconnected,
                command_id=interrupt_id,
                graph_resume_token=resume_token,
                trace_context=command.get("trace_context"),
            ):
                yield event
        except WriteCommandError as exc:
            if not confirmation_recorded:
                agent_observability.telemetry.record_confirmation(
                    action=confirmation_action,
                    outcome="failed",
                    error_type=exc.code,
                )
            yield {
                "type": "error",
                "code": exc.code,
                "message": str(exc),
                "retryable": False,
            }

    async def _persisted_stream(
        self,
        source: AsyncIterator[dict],
        *,
        user_id: str,
        conversation_id: str,
        is_disconnected: Callable[[], Awaitable[bool]],
        command_id: str | None = None,
        graph_resume_token: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> AsyncIterator[dict]:
        started_at = agent_observability.telemetry.now()
        chunks: list[str] = []
        awaiting_confirmation = False
        first_token_recorded = False
        outcome = "completed"
        error_type = None
        attributes = {"app.conversation_id": conversation_id}
        if command_id is not None:
            attributes["app.command_id"] = command_id
        links = agent_observability.links_from_trace_context(trace_context)
        agent_observability.telemetry.change_sse_connections(
            1,
            model=settings.MODEL_NAME,
        )
        try:
            with agent_observability.telemetry.start_span(
                "agent.run",
                attributes=attributes,
                links=links,
            ) as span:
                try:
                    try:
                        async with asyncio.timeout(self.timeout_seconds):
                            async for event in source:
                                if await is_disconnected():
                                    outcome = "disconnected"
                                    return
                                if event.get("type") == "token":
                                    chunks.append(str(event.get("delta", "")))
                                    if not first_token_recorded:
                                        first_token_recorded = True
                                        first_token_duration = (
                                            agent_observability.telemetry.elapsed(
                                                started_at
                                            )
                                        )
                                        agent_observability.telemetry.record_first_token(
                                            first_token_duration,
                                            model=settings.MODEL_NAME,
                                        )
                                        if span.is_recording():
                                            span.add_event(
                                                "agent.first_token",
                                                {"duration": first_token_duration},
                                            )
                                elif event.get("type") == "confirmation_required":
                                    awaiting_confirmation = True
                                    outcome = "awaiting_confirmation"
                                elif event.get("type") == "error":
                                    outcome = "error"
                                    error_type = str(
                                        event.get("code") or "AGENT_STREAM_ERROR"
                                    )
                                yield event
                    except asyncio.CancelledError:
                        outcome = "cancelled"
                        raise
                    except TimeoutError as exc:
                        outcome = "timeout"
                        error_type = type(exc).__name__
                        agent_observability.telemetry.record_exception(span, exc)
                        logger.exception(
                            "Agent run timed out conversation_id=%s",
                            conversation_id,
                        )
                        yield {
                            "type": "error",
                            "code": "CHAT_MODEL_UNAVAILABLE",
                            "message": "智能客服暂时不可用，请稍后重试",
                            "retryable": True,
                        }
                        return
                    except Exception as exc:
                        outcome = "error"
                        error_type = type(exc).__name__
                        agent_observability.telemetry.record_exception(span, exc)
                        logger.exception(
                            "Agent run failed conversation_id=%s",
                            conversation_id,
                        )
                        yield {
                            "type": "error",
                            "code": "CHAT_MODEL_UNAVAILABLE",
                            "message": "智能客服暂时不可用，请稍后重试",
                            "retryable": True,
                        }
                        return

                    response_text = "".join(chunks).strip()
                    message_id = None
                    with agent_observability.telemetry.start_span(
                        "conversation.persist",
                        attributes={"app.conversation_id": conversation_id},
                    ) as persist_span:
                        try:
                            if response_text:
                                message_kwargs = {
                                    "conversation_id": conversation_id,
                                    "user_id": user_id,
                                    "role": "assistant",
                                    "content": response_text,
                                }
                                if command_id is not None:
                                    message_kwargs["message_id"] = (
                                        f"write-command:{command_id}:assistant"
                                    )
                                message_id = await self.repository.append_message(
                                    **message_kwargs
                                )
                            if command_id is not None:
                                await self.command_service.mark_graph_completed(
                                    command_id=command_id,
                                    user_id=user_id,
                                    response_text=response_text,
                                    assistant_message_id=message_id,
                                    resume_token=graph_resume_token,
                                )
                        except Exception as exc:
                            agent_observability.telemetry.record_exception(
                                persist_span,
                                exc,
                            )
                            raise
                    yield {
                        "type": "done",
                        "outcome": (
                            "awaiting_confirmation"
                            if awaiting_confirmation
                            else "completed"
                        ),
                        "message_id": message_id,
                    }
                except asyncio.CancelledError:
                    outcome = "cancelled"
                    raise
                except Exception as exc:
                    outcome = "error"
                    error_type = type(exc).__name__
                    agent_observability.telemetry.record_exception(span, exc)
                    raise
                finally:
                    agent_observability.telemetry.set_outcome(
                        span,
                        outcome,
                        error_type=error_type,
                    )
        finally:
            agent_observability.telemetry.record_agent_run(
                agent_observability.telemetry.elapsed(started_at),
                outcome=outcome,
                model=settings.MODEL_NAME,
                error_type=error_type,
            )
            agent_observability.telemetry.change_sse_connections(
                -1,
                model=settings.MODEL_NAME,
            )

    async def _replay_command_response(
        self,
        *,
        command: dict,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[dict]:
        response_text = str(command.get("assistant_response") or "").strip()
        message_id = command.get("assistant_message_id")
        if not response_text:
            result = command.get("result") or {}
            if result.get("ok"):
                response_text = "操作已完成。"
            else:
                response_text = str(result.get("message") or "本次操作未能完成。")
            message_id = await self.repository.append_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="assistant",
                content=response_text,
                message_id=f"write-command:{command['command_id']}:assistant",
            )
            await self.command_service.mark_graph_completed(
                command_id=command["command_id"],
                user_id=user_id,
                response_text=response_text,
                assistant_message_id=message_id,
            )
        if response_text:
            yield {"type": "token", "delta": response_text}
        yield {
            "type": "done",
            "outcome": "completed",
            "message_id": message_id,
            "replayed": True,
        }

    @staticmethod
    def _title_from_message(message: str) -> str:
        normalized = " ".join(message.split())
        return normalized[:30] or "新会话"
