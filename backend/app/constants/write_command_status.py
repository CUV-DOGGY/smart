from enum import Enum


class WriteCommandStatus(str, Enum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    EXECUTING = "executing"
    RETRY_PENDING = "retry_pending"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONFLICT = "conflict"
    FAILED = "failed"


TERMINAL_WRITE_COMMAND_STATUSES = frozenset(
    {
        WriteCommandStatus.SUCCEEDED,
        WriteCommandStatus.REJECTED,
        WriteCommandStatus.EXPIRED,
        WriteCommandStatus.CONFLICT,
        WriteCommandStatus.FAILED,
    }
)


WRITE_COMMAND_TRANSITIONS = {
    WriteCommandStatus.AWAITING_CONFIRMATION: {
        WriteCommandStatus.APPROVED,
        WriteCommandStatus.REJECTED,
        WriteCommandStatus.EXPIRED,
    },
    WriteCommandStatus.APPROVED: {WriteCommandStatus.EXECUTING},
    WriteCommandStatus.RETRY_PENDING: {WriteCommandStatus.EXECUTING},
    WriteCommandStatus.EXECUTING: {
        WriteCommandStatus.SUCCEEDED,
        WriteCommandStatus.CONFLICT,
        WriteCommandStatus.RETRY_PENDING,
        WriteCommandStatus.FAILED,
    },
    WriteCommandStatus.SUCCEEDED: set(),
    WriteCommandStatus.REJECTED: set(),
    WriteCommandStatus.EXPIRED: set(),
    WriteCommandStatus.CONFLICT: set(),
    WriteCommandStatus.FAILED: set(),
}


def is_terminal_write_command_status(status: str | WriteCommandStatus) -> bool:
    try:
        normalized = WriteCommandStatus(status)
    except ValueError:
        return False
    return normalized in TERMINAL_WRITE_COMMAND_STATUSES


def can_transition_write_command(
    current: str | WriteCommandStatus,
    target: str | WriteCommandStatus,
) -> bool:
    try:
        normalized_current = WriteCommandStatus(current)
        normalized_target = WriteCommandStatus(target)
    except ValueError:
        return False
    return normalized_target in WRITE_COMMAND_TRANSITIONS.get(
        normalized_current,
        set(),
    )
