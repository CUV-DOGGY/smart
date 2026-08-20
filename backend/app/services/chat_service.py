import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from app.agents.runner import (
    AgentConfirmationRequiredError,
    AgentConfirmationStaleError,
    AgentRunner,
)
from app.agents.runtime import AgentRuntimeContext
from app.integrations.conversation_lock import ConversationRunLock
from app.ports.repositories import ConversationRepositoryPort
from app.services.conversation_service import ConversationNotFoundError


logger = logging.getLogger(__name__)


class AgentChatService:
    def __init__(
        self,
        repository: ConversationRepositoryPort,
        runner: AgentRunner,
        run_lock: ConversationRunLock,
        runtime_context: AgentRuntimeContext,
        *,
        timeout_seconds: int,
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.run_lock = run_lock
        self.runtime_context = runtime_context
        self.timeout_seconds = timeout_seconds

    async def prepare_message(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: str | None,
    ) -> str:
        if conversation_id is None:
            return await self.repository.create_conversation(
                user_id,
                self._title_from_message(message),
            )
        if not await self.repository.is_owned_by(conversation_id, user_id):
            raise ConversationNotFoundError
        if await self.runner.pending_confirmation(user_id, conversation_id):
            raise AgentConfirmationRequiredError
        return conversation_id

    async def accept_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message: str,
    ) -> list[dict]:
        if await self.runner.pending_confirmation(user_id, conversation_id):
            raise AgentConfirmationRequiredError
        saved = await self.repository.append_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=message,
        )
        if saved is None:
            raise ConversationNotFoundError
        return await self.repository.recent_messages(
            conversation_id,
            user_id,
            limit=30,
        )

    async def ensure_resume(
        self,
        *,
        user_id: str,
        conversation_id: str,
        interrupt_id: str,
    ) -> None:
        if not await self.repository.is_owned_by(conversation_id, user_id):
            raise ConversationNotFoundError
        pending = await self.runner.pending_confirmation(user_id, conversation_id)
        if pending is None or pending.get("interrupt_id") != interrupt_id:
            raise AgentConfirmationStaleError

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
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict]:
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
        ):
            yield event

    async def _persisted_stream(
        self,
        source: AsyncIterator[dict],
        *,
        user_id: str,
        conversation_id: str,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict]:
        chunks: list[str] = []
        awaiting_confirmation = False
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for event in source:
                    if await is_disconnected():
                        return
                    if event.get("type") == "token":
                        chunks.append(str(event.get("delta", "")))
                    elif event.get("type") == "confirmation_required":
                        awaiting_confirmation = True
                    yield event
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent run failed conversation_id=%s", conversation_id)
            yield {
                "type": "error",
                "code": "CHAT_MODEL_UNAVAILABLE",
                "message": "智能客服暂时不可用，请稍后重试",
                "retryable": True,
            }
            return

        response_text = "".join(chunks).strip()
        message_id = None
        if response_text:
            message_id = await self.repository.append_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role="assistant",
                content=response_text,
            )
        yield {
            "type": "done",
            "outcome": "awaiting_confirmation" if awaiting_confirmation else "completed",
            "message_id": message_id,
        }

    @staticmethod
    def _title_from_message(message: str) -> str:
        normalized = " ".join(message.split())
        return normalized[:30] or "新会话"
