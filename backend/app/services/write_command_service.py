from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.constants.write_command_status import (
    WriteCommandStatus,
    is_terminal_write_command_status,
)


class WriteCommandError(RuntimeError):
    code = "WRITE_COMMAND_ERROR"


class WriteCommandNotFoundError(WriteCommandError):
    code = "WRITE_COMMAND_NOT_FOUND"


class WriteCommandPreparationError(WriteCommandError):
    code = "WRITE_COMMAND_PREPARATION_FAILED"

    def __init__(self, result: dict[str, Any]):
        super().__init__(str(result.get("message") or self.code))
        self.result = result


class WriteCommandProposalConflictError(WriteCommandError):
    code = "WRITE_COMMAND_PROPOSAL_CONFLICT"


class WriteCommandDecisionConflictError(WriteCommandError):
    code = "WRITE_COMMAND_DECISION_CONFLICT"


class WriteCommandIdempotencyConflictError(WriteCommandError):
    code = "WRITE_COMMAND_IDEMPOTENCY_CONFLICT"


class WriteCommandExpiredError(WriteCommandError):
    code = "WRITE_COMMAND_EXPIRED"


class WriteCommandExecutionInProgressError(WriteCommandError):
    code = "WRITE_COMMAND_EXECUTION_IN_PROGRESS"


class WriteCommandExecutionLeaseLostError(WriteCommandError):
    code = "WRITE_COMMAND_EXECUTION_LEASE_LOST"


class WriteCommandService:
    def __init__(
        self,
        repository,
        tools,
        *,
        confirmation_ttl_seconds: int = 15 * 60,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.tools = tools
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def prepare(
        self,
        *,
        command_id: str,
        user_id: str,
        conversation_id: str,
        action: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        request_hash = self.request_hash(action, arguments)
        existing = await self.repository.find_owned(
            command_id=command_id,
            user_id=user_id,
        )
        if existing is not None:
            self._assert_same_proposal(
                existing,
                action,
                request_hash,
                user_id,
                conversation_id,
            )
            return existing

        confirmation = await self.tools.prepare_confirmation(
            action,
            arguments,
            user_id=user_id,
        )
        if not confirmation.get("ok"):
            raise WriteCommandPreparationError(confirmation)

        now = self._now()
        presentation = confirmation.get("presentation")
        document = {
            "command_id": command_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "action": action,
            "arguments": arguments,
            "request_hash": request_hash,
            "confirmation_hash": self.confirmation_hash(
                confirmation["summary"],
                presentation,
            ),
            "status": WriteCommandStatus.AWAITING_CONFIRMATION.value,
            "version": 1,
            "summary": confirmation["summary"],
            "presentation": presentation,
            "decision": None,
            "decision_idempotency_key": None,
            "decision_request_hash": None,
            "attempt_count": 0,
            "next_attempt_at": None,
            "execution_token": None,
            "lease_until": None,
            "result": None,
            "error": None,
            "graph_resume_status": "pending",
            "graph_resume_token": None,
            "graph_resume_lease_until": None,
            "assistant_response": None,
            "assistant_message_id": None,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(seconds=self.confirmation_ttl_seconds),
            "decided_at": None,
            "started_at": None,
            "finished_at": None,
        }
        created = await self.repository.create(document)
        self._assert_same_proposal(
            created,
            action,
            request_hash,
            user_id,
            conversation_id,
        )
        return created

    async def get_owned(
        self,
        *,
        command_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        command = await self.repository.find_owned(
            command_id=command_id,
            user_id=user_id,
        )
        if command is None:
            raise WriteCommandNotFoundError("Write command not found")
        return command

    async def decide(
        self,
        *,
        command_id: str,
        user_id: str,
        decision: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise WriteCommandDecisionConflictError("Unsupported decision")
        request_hash = self.decision_hash(command_id, decision)

        reused = await self.repository.find_by_decision_key(
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if reused is not None:
            if reused.get("decision_request_hash") != request_hash:
                raise WriteCommandIdempotencyConflictError(
                    "Idempotency key was used for another decision"
                )
            return reused

        command = await self.get_owned(command_id=command_id, user_id=user_id)
        current_status = command["status"]
        recorded_decision = command.get("decision")
        if current_status != WriteCommandStatus.AWAITING_CONFIRMATION.value:
            if recorded_decision == decision:
                return command
            if decision == "approve" and current_status in {
                WriteCommandStatus.APPROVED.value,
                WriteCommandStatus.EXECUTING.value,
                WriteCommandStatus.RETRY_PENDING.value,
                WriteCommandStatus.SUCCEEDED.value,
                WriteCommandStatus.CONFLICT.value,
                WriteCommandStatus.FAILED.value,
            }:
                return command
            raise WriteCommandDecisionConflictError(
                f"Command was already decided as {recorded_decision or current_status}"
            )

        now = self._now()
        if self._as_utc(command["expires_at"]) <= now:
            await self.repository.mark_expired(
                command_id=command_id,
                user_id=user_id,
                now=now,
            )
            raise WriteCommandExpiredError("Write command expired")
        target = (
            WriteCommandStatus.APPROVED
            if decision == "approve"
            else WriteCommandStatus.REJECTED
        )
        result = None
        if decision == "reject":
            result = {
                "ok": False,
                "code": "USER_REJECTED",
                "message": "用户取消了本次操作",
            }
        updated = await self.repository.decide(
            command_id=command_id,
            user_id=user_id,
            expected_status=WriteCommandStatus.AWAITING_CONFIRMATION.value,
            target_status=target.value,
            decision=decision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            now=now,
            result=result,
        )
        if updated is not None:
            return updated

        reused = await self.repository.find_by_decision_key(
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if reused is not None:
            if reused.get("decision_request_hash") != request_hash:
                raise WriteCommandIdempotencyConflictError(
                    "Idempotency key was used for another decision"
                )
            return reused

        current = await self.get_owned(command_id=command_id, user_id=user_id)
        if current.get("decision") == decision:
            return current
        if current.get("decision") in {"approve", "reject"}:
            raise WriteCommandDecisionConflictError(
                f"Command was already decided as {current['decision']}"
            )
        raise WriteCommandDecisionConflictError("Write command changed concurrently")

    async def mark_graph_resuming(
        self,
        *,
        command_id: str,
        user_id: str,
        resume_token: str,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        now = self._now()
        updated = await self.repository.mark_graph_resuming(
            command_id=command_id,
            user_id=user_id,
            resume_token=resume_token,
            now=now,
            lease_until=now + timedelta(seconds=lease_seconds),
        )
        if updated is not None:
            return updated
        return await self.get_owned(command_id=command_id, user_id=user_id)

    async def mark_graph_completed(
        self,
        *,
        command_id: str,
        user_id: str,
        response_text: str,
        assistant_message_id: str | None,
        resume_token: str | None = None,
    ) -> dict[str, Any]:
        updated = await self.repository.mark_graph_completed(
            command_id=command_id,
            user_id=user_id,
            response_text=response_text,
            assistant_message_id=assistant_message_id,
            now=self._now(),
            resume_token=resume_token,
        )
        if updated is None:
            raise WriteCommandNotFoundError("Write command not found")
        return updated

    @staticmethod
    def result_for_agent(command: dict[str, Any]) -> dict[str, Any]:
        if not is_terminal_write_command_status(command["status"]):
            raise WriteCommandExecutionInProgressError(
                "Write command has not reached a terminal state"
            )
        result = command.get("result")
        if isinstance(result, dict):
            return result
        return {
            "ok": False,
            "code": "WRITE_COMMAND_RESULT_MISSING",
            "message": "写操作没有可用的执行结果",
        }

    @staticmethod
    def request_hash(action: str, arguments: dict[str, Any]) -> str:
        return WriteCommandService._hash_json(
            {"action": action, "arguments": arguments}
        )

    @staticmethod
    def decision_hash(command_id: str, decision: str) -> str:
        return WriteCommandService._hash_json(
            {"command_id": command_id, "decision": decision}
        )

    @staticmethod
    def confirmation_hash(
        summary: str,
        presentation: dict[str, Any] | None,
    ) -> str:
        return WriteCommandService._hash_json(
            {"summary": summary, "presentation": presentation}
        )

    @staticmethod
    def _hash_json(value: Any) -> str:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _assert_same_proposal(
        command: dict[str, Any],
        action: str,
        request_hash: str,
        user_id: str,
        conversation_id: str,
    ) -> None:
        if (
            command.get("action") != action
            or command.get("request_hash") != request_hash
            or command.get("user_id") != user_id
            or command.get("conversation_id") != conversation_id
        ):
            raise WriteCommandProposalConflictError(
                "Command identifier was reused for a different proposal"
            )

    def _now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            raise RuntimeError("now_provider must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
