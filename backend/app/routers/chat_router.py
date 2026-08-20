import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.agents.runner import (
    AgentConfirmationRequiredError,
    AgentConfirmationStaleError,
)
from app.agents.runtime import AgentRuntimeContext
from app.core.api_errors import ApiError
from app.dependencies.auth import get_current_user_id
from app.dependencies.services import (
    get_agent_chat_service,
    get_conversation_service,
)
from app.integrations.conversation_lock import ConversationBusyError
from app.schemas.conversation import (
    ChatResumeRequest,
    ChatStreamRequest,
    ConversationListResponse,
    ConversationMessageListResponse,
    PendingConfirmation,
)
from app.services.chat_service import AgentChatService
from app.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)


chat_router = APIRouter(prefix="/chat", tags=["智能客服 Agent"])
conversation_router = APIRouter(prefix="/conversations", tags=["客服会话"])


@chat_router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[AgentChatService, Depends(get_agent_chat_service)],
) -> StreamingResponse:
    conversation_id = await _prepare_message(service, payload, user_id)
    service.runtime_context = AgentRuntimeContext(
        user_id=user_id,
        llm=service.runtime_context.llm,
        tools=service.runtime_context.tools,
    )
    lock_context = service.run_lock.acquire(user_id, conversation_id)
    try:
        await lock_context.__aenter__()
    except ConversationBusyError as exc:
        raise ApiError(409, "CONVERSATION_BUSY", "会话正在处理中，请稍后重试") from exc
    try:
        history = await service.accept_message(
            user_id=user_id,
            conversation_id=conversation_id,
            message=payload.message,
        )
    except Exception:
        await lock_context.__aexit__(None, None, None)
        raise

    return _streaming_response(
        request,
        conversation_id,
        service.stream_message(
            user_id=user_id,
            conversation_id=conversation_id,
            message=payload.message,
            history=history,
            is_disconnected=request.is_disconnected,
        ),
        lock_context,
    )


@chat_router.post("/resume")
async def resume_chat(
    payload: ChatResumeRequest,
    request: Request,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[AgentChatService, Depends(get_agent_chat_service)],
) -> StreamingResponse:
    service.runtime_context = AgentRuntimeContext(
        user_id=user_id,
        llm=service.runtime_context.llm,
        tools=service.runtime_context.tools,
    )
    await _ensure_resume(service, payload, user_id)
    lock_context = service.run_lock.acquire(user_id, payload.conversation_id)
    try:
        await lock_context.__aenter__()
    except ConversationBusyError as exc:
        raise ApiError(409, "CONVERSATION_BUSY", "会话正在处理中，请稍后重试") from exc
    try:
        await _ensure_resume(service, payload, user_id)
    except Exception:
        await lock_context.__aexit__(None, None, None)
        raise
    return _streaming_response(
        request,
        payload.conversation_id,
        service.stream_resume(
            user_id=user_id,
            conversation_id=payload.conversation_id,
            interrupt_id=payload.interrupt_id,
            decision=payload.decision,
            is_disconnected=request.is_disconnected,
        ),
        lock_context,
    )


@conversation_router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> ConversationListResponse:
    try:
        return await service.list(user_id, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise ApiError(422, "INVALID_CURSOR", "分页游标无效") from exc


@conversation_router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
)
async def list_messages(
    conversation_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationMessageListResponse:
    try:
        response = await service.messages(conversation_id, user_id)
    except ConversationNotFoundError as exc:
        raise _not_found() from exc
    pending = await request.app.state.agent_runner.pending_confirmation(
        user_id, conversation_id
    )
    if pending:
        response.pending_confirmation = PendingConfirmation.model_validate(pending)
    return response


@conversation_router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Response:
    try:
        await service.delete(conversation_id, user_id)
    except ConversationNotFoundError as exc:
        raise _not_found() from exc
    await request.app.state.agent_runner.delete_thread(user_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _prepare_message(
    service: AgentChatService,
    payload: ChatStreamRequest,
    user_id: str,
) -> str:
    try:
        return await service.prepare_message(
            user_id=user_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
    except ConversationNotFoundError as exc:
        raise _not_found() from exc
    except AgentConfirmationRequiredError as exc:
        raise ApiError(
            409,
            "AGENT_CONFIRMATION_REQUIRED",
            "请先处理当前待确认操作",
        ) from exc


async def _ensure_resume(
    service: AgentChatService,
    payload: ChatResumeRequest,
    user_id: str,
) -> None:
    try:
        await service.ensure_resume(
            user_id=user_id,
            conversation_id=payload.conversation_id,
            interrupt_id=payload.interrupt_id,
        )
    except ConversationNotFoundError as exc:
        raise _not_found() from exc
    except AgentConfirmationStaleError as exc:
        raise ApiError(
            409,
            "AGENT_CONFIRMATION_STALE",
            "待确认操作已失效或已处理",
        ) from exc


def _streaming_response(
    request: Request,
    conversation_id: str,
    source: AsyncIterator[dict],
    lock_context,
) -> StreamingResponse:
    request_id = request.state.request_id
    run_id = str(uuid.uuid4())

    async def events() -> AsyncIterator[str]:
        try:
            yield _sse({"type": "meta", "conversation_id": conversation_id, "run_id": run_id})
            async for event in source:
                if event.get("type") == "error":
                    event["request_id"] = request_id
                yield _sse(event)
        finally:
            await lock_context.__aexit__(None, None, None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _not_found() -> ApiError:
    return ApiError(404, "CONVERSATION_NOT_FOUND", "会话不存在或无权访问")


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
