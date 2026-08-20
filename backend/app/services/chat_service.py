import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from app.repositories.conversation_repository import ConversationRepository


logger = logging.getLogger(__name__)
SYSTEM_PROMPT = (
    "你是 SmartServe 外卖平台客服。请使用简洁、准确、友好的中文回答。"
    "本阶段没有业务工具，禁止声称已经修改订单、退款或地址；需要操作时应引导用户前往对应页面。"
)


class ConversationNotFoundError(RuntimeError):
    pass


class ChatService:
    def __init__(self, repository: ConversationRepository, llm) -> None:
        self.repository = repository
        self.llm = llm

    async def prepare(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: str | None,
    ) -> tuple[str, list[dict]]:
        if conversation_id is None:
            conversation_id = await self.repository.create_conversation(
                user_id,
                self._title_from_message(message),
            )
        elif not await self.repository.is_owned_by(conversation_id, user_id):
            raise ConversationNotFoundError

        saved = await self.repository.append_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=message,
        )
        if saved is None:
            raise ConversationNotFoundError
        history = await self.repository.recent_messages(
            conversation_id,
            user_id,
            limit=20,
        )
        return conversation_id, history

    async def stream_reply(
        self,
        *,
        conversation_id: str,
        user_id: str,
        history: list[dict],
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict[str, object]]:
        messages = [("system", SYSTEM_PROMPT)]
        messages.extend(
            (document["role"], document["content"])
            for document in history
            if document.get("role") in {"user", "assistant"}
        )
        chunks: list[str] = []
        try:
            async with asyncio.timeout(60):
                async for chunk in self.llm.astream(messages):
                    if await is_disconnected():
                        return
                    delta = self._chunk_text(getattr(chunk, "content", ""))
                    if not delta:
                        continue
                    chunks.append(delta)
                    yield {"type": "token", "delta": delta}
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Chat model stream failed conversation_id=%s",
                conversation_id,
            )
            yield {
                "type": "error",
                "code": "CHAT_MODEL_UNAVAILABLE",
                "message": "智能客服暂时不可用，请稍后重试",
            }
            return

        response_text = "".join(chunks).strip()
        if not response_text:
            yield {
                "type": "error",
                "code": "CHAT_EMPTY_RESPONSE",
                "message": "智能客服未返回有效内容，请重试",
            }
            return
        message_id = await self.repository.append_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=response_text,
        )
        if message_id is None:
            yield {
                "type": "error",
                "code": "CONVERSATION_NOT_FOUND",
                "message": "会话不存在或已被删除",
            }
            return
        yield {"type": "done", "message_id": message_id}

    @staticmethod
    def _title_from_message(message: str) -> str:
        normalized = " ".join(message.split())
        return normalized[:30] or "新会话"

    @staticmethod
    def _chunk_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(item["text"])
            return "".join(texts)
        return ""
