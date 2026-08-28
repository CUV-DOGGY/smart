from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.constants.write_command_status import (
    WriteCommandStatus,
    is_terminal_write_command_status,
)
from app.observability import agent as agent_observability
from app.services.write_command_service import (
    WriteCommandExecutionInProgressError,
    WriteCommandExecutionLeaseLostError,
    WriteCommandNotFoundError,
    WriteCommandService,
)


logger = logging.getLogger(__name__)


CONFLICT_RESULT_CODES = frozenset(
    {
        "ADDRESS_NOT_FOUND",
        "ADDRESS_LIMIT_REACHED",
        "ORDER_NOT_FOUND",
        "ORDER_STATE_CONFLICT",
        "PRODUCT_NOT_FOUND",
        "SHOP_NOT_FOUND",
        "SHOP_UNAVAILABLE",
        "SHOP_CLOSED",
        "PRODUCT_UNAVAILABLE",
        "INSUFFICIENT_STOCK",
        "INVENTORY_CHANGED",
        "MINIMUM_ORDER_AMOUNT",
        "SHOP_DELIVERY_CONFIG_NOT_CONFIGURED",
        "OUTSIDE_DELIVERY_AREA",
        "IDEMPOTENCY_KEY_CONFLICT",
        "CONFIRMATION_DATA_CHANGED",
    }
)


class WriteCommandExecutor:
    def __init__(
        self,
        repository,
        tools,
        *,
        lease_seconds: int = 120,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.tools = tools
        self.lease_seconds = lease_seconds
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def execute_or_replay(
        self,
        *,
        command_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        try:
            command = await self.repository.find_owned(
                command_id=command_id,
                user_id=user_id,
            )
        except Exception as exc:
            with agent_observability.telemetry.start_span(
                "write_command.execute",
                attributes={"app.command_id": command_id},
            ) as span:
                agent_observability.telemetry.record_exception(span, exc)
                agent_observability.telemetry.set_outcome(
                    span,
                    "failed",
                    error_type=type(exc).__name__,
                )
            agent_observability.telemetry.record_write_command(
                action="unknown",
                outcome="failed",
                error_type=type(exc).__name__,
            )
            raise
        if command is None:
            error = WriteCommandNotFoundError("Write command not found")
            with agent_observability.telemetry.start_span(
                "write_command.execute",
                attributes={"app.command_id": command_id},
            ) as span:
                agent_observability.telemetry.record_exception(span, error)
                agent_observability.telemetry.set_outcome(
                    span,
                    "not_found",
                    error_type=error.code,
                )
            agent_observability.telemetry.record_write_command(
                action="unknown",
                outcome="not_found",
                error_type=error.code,
            )
            raise error

        action = str(command.get("action") or "unknown")
        was_terminal = is_terminal_write_command_status(command["status"])
        links = agent_observability.links_from_trace_context(
            command.get("trace_context")
        )
        outcome = "failed"
        error_type = None
        with agent_observability.telemetry.start_span(
            "write_command.execute",
            attributes={
                "app.command_id": command_id,
                "agent.action": action,
                "write_command.initial_status": command["status"],
            },
            links=links,
        ) as span:
            try:
                result = await self._execute_loaded(
                    command,
                    command_id=command_id,
                    user_id=user_id,
                )
                if was_terminal:
                    outcome = "replayed"
                else:
                    outcome = str(result.get("status") or "unknown")
                    if outcome in {
                        WriteCommandStatus.CONFLICT.value,
                        WriteCommandStatus.FAILED.value,
                    }:
                        command_result = result.get("result")
                        if isinstance(command_result, dict):
                            error_type = str(
                                command_result.get("code") or "COMMAND_FAILED"
                            )
                return result
            except Exception as exc:
                error_type = getattr(exc, "code", type(exc).__name__)
                if isinstance(exc, WriteCommandExecutionInProgressError):
                    outcome = "in_progress"
                elif isinstance(exc, WriteCommandExecutionLeaseLostError):
                    outcome = "lease_lost"
                elif isinstance(exc, WriteCommandNotFoundError):
                    outcome = "not_found"
                else:
                    outcome = "failed"
                agent_observability.telemetry.record_exception(span, exc)
                raise
            finally:
                agent_observability.telemetry.set_outcome(
                    span,
                    outcome,
                    error_type=error_type,
                )
                agent_observability.telemetry.record_write_command(
                    action=action,
                    outcome=outcome,
                    error_type=error_type,
                )

    async def _execute_loaded(
        self,
        command: dict[str, Any],
        *,
        command_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        if is_terminal_write_command_status(command["status"]):
            return command
        if command["status"] == WriteCommandStatus.AWAITING_CONFIRMATION.value:
            raise WriteCommandExecutionInProgressError(
                "Write command has not been approved"
            )

        now = self._now()
        execution_token = str(uuid.uuid4())
        claimed = await self.repository.claim_execution(
            command_id=command_id,
            user_id=user_id,
            execution_token=execution_token,
            now=now,
            lease_until=now + timedelta(seconds=self.lease_seconds),
        )
        if claimed is None:
            current = await self.repository.find_owned(
                command_id=command_id,
                user_id=user_id,
            )
            if current is None:
                raise WriteCommandNotFoundError("Write command not found")
            if is_terminal_write_command_status(current["status"]):
                return current
            raise WriteCommandExecutionInProgressError(
                "Write command is already executing"
            )

        try:
            confirmation = await self.tools.prepare_confirmation(
                claimed["action"],
                claimed["arguments"],
                user_id=user_id,
            )
            if not confirmation.get("ok"):
                result = confirmation
                return await self._finish_without_business_write(
                    claimed,
                    execution_token,
                    result,
                    WriteCommandStatus.CONFLICT,
                )
            current_confirmation_hash = WriteCommandService.confirmation_hash(
                confirmation["summary"],
                confirmation.get("presentation"),
            )
            if current_confirmation_hash != claimed.get("confirmation_hash"):
                return await self._finish_without_business_write(
                    claimed,
                    execution_token,
                    {
                        "ok": False,
                        "code": "CONFIRMATION_DATA_CHANGED",
                        "message": "确认内容已经变化，请重新确认",
                    },
                    WriteCommandStatus.CONFLICT,
                )

            async def execute_in_transaction(session):
                locked = await self.repository.find_executing(
                    command_id=command_id,
                    user_id=user_id,
                    execution_token=execution_token,
                    session=session,
                )
                if locked is None:
                    raise WriteCommandExecutionLeaseLostError(
                        "Write command execution lease was lost"
                    )
                result = await self.tools.execute_write(
                    locked["action"],
                    locked["arguments"],
                    user_id=user_id,
                    command_id=command_id,
                    session=session,
                )
                target = (
                    WriteCommandStatus.SUCCEEDED
                    if result.get("ok")
                    else self._failure_status(result)
                )
                completed = await self.repository.mark_terminal(
                    command_id=command_id,
                    user_id=user_id,
                    execution_token=execution_token,
                    status=target.value,
                    result=result,
                    now=self._now(),
                    session=session,
                )
                if completed is None:
                    raise WriteCommandExecutionLeaseLostError(
                        "Write command execution lease was lost"
                    )
                return completed

            return await self.repository.run_in_transaction(execute_in_transaction)
        except WriteCommandExecutionLeaseLostError:
            raise
        except Exception as exc:
            business_failure = self.tools.business_failure(exc)
            if business_failure is not None:
                return await self._finish_without_business_write(
                    claimed,
                    execution_token,
                    business_failure,
                    self._failure_status(business_failure),
                )
            logger.exception("Write command execution failed command_id=%s", command_id)
            error = {
                "code": "WRITE_COMMAND_EXECUTION_FAILED",
                "message": "写操作暂时无法完成，请稍后重试",
                "type": type(exc).__name__,
            }
            failed = await self.repository.mark_failed(
                command_id=command_id,
                user_id=user_id,
                execution_token=execution_token,
                error=error,
                now=self._now(),
            )
            if failed is not None:
                return failed
            current = await self.repository.find_owned(
                command_id=command_id,
                user_id=user_id,
            )
            if current is not None and is_terminal_write_command_status(
                current["status"]
            ):
                return current
            raise

    async def _finish_without_business_write(
        self,
        command: dict[str, Any],
        execution_token: str,
        result: dict[str, Any],
        target: WriteCommandStatus,
    ) -> dict[str, Any]:
        async def finish(session):
            completed = await self.repository.mark_terminal(
                command_id=command["command_id"],
                user_id=command["user_id"],
                execution_token=execution_token,
                status=target.value,
                result=result,
                now=self._now(),
                session=session,
            )
            if completed is None:
                raise WriteCommandExecutionLeaseLostError(
                    "Write command execution lease was lost"
                )
            return completed

        return await self.repository.run_in_transaction(finish)

    @staticmethod
    def _failure_status(result: dict[str, Any]) -> WriteCommandStatus:
        return (
            WriteCommandStatus.CONFLICT
            if result.get("code") in CONFLICT_RESULT_CODES
            else WriteCommandStatus.FAILED
        )

    def _now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)
