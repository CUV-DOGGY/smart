import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.core.api_errors import ApiError
from app.dependencies.auth import get_current_user_id
from app.dependencies.database import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import (
    ChatStreamRequest,
    ConversationListResponse,
    ConversationMessage,
    ConversationMessageListResponse,
    ConversationSummary,
)
from app.services.chat_service import ChatService, ConversationNotFoundError


chat_router = APIRouter(prefix="/chat", tags=["智能客服"])
conversation_router = APIRouter(prefix="/conversations", tags=["客服会话"])


def get_repository(db=Depends(get_db)) -> ConversationRepository:
    return ConversationRepository(db)


@chat_router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ConversationRepository, Depends(get_repository)],
) -> StreamingResponse:
    service = ChatService(repository, request.app.state.llm)
    try:
        conversation_id, history = await service.prepare(
            user_id=user_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
    except ConversationNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSATION_NOT_FOUND",
            message="会话不存在或无权访问",
        ) from exc

    request_id = request.state.request_id

    async def events() -> AsyncIterator[str]:
        yield _sse(
            {
                "type": "meta",
                "conversation_id": conversation_id,
            }
        )
        async for event in service.stream_reply(
            conversation_id=conversation_id,
            user_id=user_id,
            history=history,
            is_disconnected=request.is_disconnected,
        ):
            if event.get("type") == "error":
                event["request_id"] = request_id
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@conversation_router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ConversationRepository, Depends(get_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ConversationListResponse:
    try:
        documents, next_cursor = await repository.list_conversations(
            user_id,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_CURSOR",
            message="分页游标无效",
        ) from exc
    return ConversationListResponse(
        items=[ConversationSummary.model_validate(item) for item in documents],
        next_cursor=next_cursor,
    )


@conversation_router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
)
async def list_messages(
    conversation_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ConversationRepository, Depends(get_repository)],
) -> ConversationMessageListResponse:
    if not await repository.is_owned_by(conversation_id, user_id):
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSATION_NOT_FOUND",
            message="会话不存在或无权访问",
        )
    documents = await repository.recent_messages(
        conversation_id,
        user_id,
        limit=200,
    )
    return ConversationMessageListResponse(
        items=[ConversationMessage.model_validate(item) for item in documents]
    )


@conversation_router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    repository: Annotated[ConversationRepository, Depends(get_repository)],
) -> Response:
    if not await repository.delete_conversation(conversation_id, user_id):
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSATION_NOT_FOUND",
            message="会话不存在或无权访问",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
