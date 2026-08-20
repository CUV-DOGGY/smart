from app.ports.repositories import ConversationRepositoryPort
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationMessage,
    ConversationMessageListResponse,
    ConversationSummary,
)


class ConversationNotFoundError(RuntimeError):
    pass


class ConversationService:
    def __init__(self, repository: ConversationRepositoryPort) -> None:
        self.repository = repository

    async def ensure_owned(self, conversation_id: str, user_id: str) -> None:
        if not await self.repository.is_owned_by(conversation_id, user_id):
            raise ConversationNotFoundError

    async def list(
        self, user_id: str, *, limit: int, cursor: str | None
    ) -> ConversationListResponse:
        documents, next_cursor = await self.repository.list_conversations(
            user_id, limit=limit, cursor=cursor
        )
        return ConversationListResponse(
            items=[ConversationSummary.model_validate(item) for item in documents],
            next_cursor=next_cursor,
        )

    async def messages(
        self, conversation_id: str, user_id: str
    ) -> ConversationMessageListResponse:
        await self.ensure_owned(conversation_id, user_id)
        documents = await self.repository.recent_messages(
            conversation_id, user_id, limit=200
        )
        return ConversationMessageListResponse(
            items=[ConversationMessage.model_validate(item) for item in documents]
        )

    async def delete(self, conversation_id: str, user_id: str) -> None:
        if not await self.repository.delete_conversation(conversation_id, user_id):
            raise ConversationNotFoundError
