from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.order import OrderConfirmationPreview


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conversation_id: str = Field(min_length=1, max_length=64)
    interrupt_id: str = Field(min_length=1, max_length=64)
    decision: Literal["approve", "reject"]


class PendingConfirmation(BaseModel):
    interrupt_id: str
    command_id: str
    action: str
    summary: str
    status: Literal["awaiting_confirmation"]
    expires_at: datetime
    presentation: OrderConfirmationPreview | None = None


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class ConversationMessage(BaseModel):
    message_id: str
    role: str
    content: str
    created_at: datetime


class ConversationMessageListResponse(BaseModel):
    items: list[ConversationMessage]
    pending_confirmation: PendingConfirmation | None = None
