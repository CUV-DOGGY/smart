from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.write_command_status import WriteCommandStatus
from app.schemas.order import (
    OrderCancellationConfirmationPreview,
    OrderConfirmationPreview,
)


WriteCommandPresentation = (
    OrderConfirmationPreview | OrderCancellationConfirmationPreview
)


class WriteCommandConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupt_id: str = Field(min_length=1, max_length=64)
    command_id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=500)
    status: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    version: int = Field(ge=1)
    expires_at: datetime
    presentation: WriteCommandPresentation | None = None


class WriteCommandView(BaseModel):
    command_id: str
    action: str
    status: WriteCommandStatus
    version: int
    summary: str
    presentation: WriteCommandPresentation | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None
    finished_at: datetime | None = None
