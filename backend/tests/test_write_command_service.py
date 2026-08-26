import copy
import unittest
from datetime import datetime, timezone

from app.constants.write_command_status import WriteCommandStatus
from app.services.write_command_executor import WriteCommandExecutor
from app.services.write_command_service import (
    WriteCommandIdempotencyConflictError,
    WriteCommandProposalConflictError,
    WriteCommandService,
)


class FakeWriteCommandRepository:
    def __init__(self):
        self.commands = {}

    async def create(self, document):
        existing = self.commands.get(document["command_id"])
        if existing is not None:
            return copy.deepcopy(existing)
        self.commands[document["command_id"]] = copy.deepcopy(document)
        return copy.deepcopy(document)

    async def find_by_command_id(self, command_id, session=None):
        command = self.commands.get(command_id)
        return copy.deepcopy(command) if command else None

    async def find_owned(self, *, command_id, user_id, session=None):
        command = self.commands.get(command_id)
        if command is None or command["user_id"] != user_id:
            return None
        return copy.deepcopy(command)

    async def find_by_decision_key(self, *, user_id, idempotency_key):
        for command in self.commands.values():
            if (
                command["user_id"] == user_id
                and command.get("decision_idempotency_key") == idempotency_key
            ):
                return copy.deepcopy(command)
        return None

    async def decide(self, **kwargs):
        for other in self.commands.values():
            if (
                other["user_id"] == kwargs["user_id"]
                and other.get("decision_idempotency_key")
                == kwargs["idempotency_key"]
                and other["command_id"] != kwargs["command_id"]
            ):
                return None
        command = self.commands[kwargs["command_id"]]
        if (
            command["user_id"] != kwargs["user_id"]
            or command["status"] != kwargs["expected_status"]
            or command["expires_at"] <= kwargs["now"]
        ):
            return None
        command.update(
            {
                "status": kwargs["target_status"],
                "decision": kwargs["decision"],
                "decision_idempotency_key": kwargs["idempotency_key"],
                "decision_request_hash": kwargs["request_hash"],
                "decided_at": kwargs["now"],
                "updated_at": kwargs["now"],
                "version": command["version"] + 1,
            }
        )
        if kwargs["result"] is not None:
            command["result"] = kwargs["result"]
            command["finished_at"] = kwargs["now"]
        if kwargs["target_status"] == WriteCommandStatus.APPROVED.value:
            command["next_attempt_at"] = kwargs["now"]
        return copy.deepcopy(command)

    async def mark_expired(self, **kwargs):
        command = self.commands[kwargs["command_id"]]
        command["status"] = WriteCommandStatus.EXPIRED.value
        return copy.deepcopy(command)

    async def claim_execution(self, **kwargs):
        command = self.commands[kwargs["command_id"]]
        if command["status"] not in {
            WriteCommandStatus.APPROVED.value,
            WriteCommandStatus.RETRY_PENDING.value,
        }:
            return None
        command.update(
            {
                "status": WriteCommandStatus.EXECUTING.value,
                "execution_token": kwargs["execution_token"],
                "lease_until": kwargs["lease_until"],
                "started_at": kwargs["now"],
                "attempt_count": command["attempt_count"] + 1,
                "version": command["version"] + 1,
            }
        )
        return copy.deepcopy(command)

    async def find_executing(self, **kwargs):
        command = self.commands[kwargs["command_id"]]
        if (
            command["status"] != WriteCommandStatus.EXECUTING.value
            or command["execution_token"] != kwargs["execution_token"]
        ):
            return None
        return copy.deepcopy(command)

    async def mark_terminal(self, **kwargs):
        command = self.commands[kwargs["command_id"]]
        if command["execution_token"] != kwargs["execution_token"]:
            return None
        command.update(
            {
                "status": kwargs["status"],
                "result": kwargs["result"],
                "finished_at": kwargs["now"],
                "version": command["version"] + 1,
                "lease_until": None,
            }
        )
        return copy.deepcopy(command)

    async def mark_failed(self, **kwargs):
        command = self.commands[kwargs["command_id"]]
        command["status"] = WriteCommandStatus.FAILED.value
        command["result"] = {
            "ok": False,
            "code": kwargs["error"]["code"],
            "message": kwargs["error"]["message"],
        }
        return copy.deepcopy(command)

    async def run_in_transaction(self, callback):
        return await callback(object())


class FakeTools:
    def __init__(self):
        self.write_calls = []

    async def prepare_confirmation(self, action, arguments, *, user_id):
        return {
            "ok": True,
            "summary": f"确认 {action}:{arguments}",
        }

    async def execute_write(
        self,
        action,
        arguments,
        *,
        user_id,
        command_id,
        session,
    ):
        self.write_calls.append((action, arguments, user_id, command_id, session))
        return {"ok": True, "action": action, "value": arguments}


class WriteCommandServiceTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        repository = FakeWriteCommandRepository()
        tools = FakeTools()
        service = WriteCommandService(repository, tools)
        return repository, tools, service

    async def prepare(self, service, command_id="command-001", arguments=None):
        return await service.prepare(
            command_id=command_id,
            user_id="user-001",
            conversation_id="conversation-001",
            action="cancel_order",
            arguments=arguments or {"order_id": "order-001"},
        )

    async def test_prepare_replays_same_command_and_rejects_changed_payload(self):
        _, _, service = self.make()
        first = await self.prepare(service)
        second = await self.prepare(service)
        self.assertEqual(first["request_hash"], second["request_hash"])

        with self.assertRaises(WriteCommandProposalConflictError):
            await self.prepare(
                service,
                arguments={"order_id": "order-002"},
            )

    async def test_decision_idempotency_key_cannot_be_reused_for_another_command(self):
        _, _, service = self.make()
        first = await self.prepare(service)
        await self.prepare(service, command_id="command-002")
        approved = await service.decide(
            command_id=first["command_id"],
            user_id="user-001",
            decision="approve",
            idempotency_key="decision-key-001",
        )
        replayed = await service.decide(
            command_id=first["command_id"],
            user_id="user-001",
            decision="approve",
            idempotency_key="decision-key-001",
        )
        self.assertEqual(approved["command_id"], replayed["command_id"])

        with self.assertRaises(WriteCommandIdempotencyConflictError):
            await service.decide(
                command_id="command-002",
                user_id="user-001",
                decision="approve",
                idempotency_key="decision-key-001",
            )

    async def test_executor_commits_once_and_replays_terminal_result(self):
        repository, tools, service = self.make()
        command = await self.prepare(service)
        await service.decide(
            command_id=command["command_id"],
            user_id="user-001",
            decision="approve",
            idempotency_key="decision-key-001",
        )
        executor = WriteCommandExecutor(repository, tools)

        first = await executor.execute_or_replay(
            command_id=command["command_id"],
            user_id="user-001",
        )
        second = await executor.execute_or_replay(
            command_id=command["command_id"],
            user_id="user-001",
        )

        self.assertEqual(first["status"], WriteCommandStatus.SUCCEEDED.value)
        self.assertEqual(second["result"], first["result"])
        self.assertEqual(len(tools.write_calls), 1)
        self.assertIsNotNone(tools.write_calls[0][-1])


if __name__ == "__main__":
    unittest.main()
