from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)


class WriteCommandWorker:
    """Recover approved commands and commands abandoned after a lost lease.

    Normal chat confirmations execute inline for low latency. The grace period
    prevents this recovery loop from racing the request that just approved a
    command; it only takes over work that appears abandoned.
    """

    def __init__(
        self,
        repository,
        executor,
        *,
        poll_seconds: float = 5.0,
        recovery_grace_seconds: int = 15,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.poll_seconds = poll_seconds
        self.recovery_grace_seconds = recovery_grace_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="write-command-recovery",
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                now = datetime.now(timezone.utc)
                commands = await self.repository.find_recoverable(
                    now=now,
                    approved_before=now
                    - timedelta(seconds=self.recovery_grace_seconds),
                )
                for command in commands:
                    if self._stop.is_set():
                        return
                    try:
                        await self.executor.execute_or_replay(
                            command_id=command["command_id"],
                            user_id=command["user_id"],
                        )
                    except Exception:
                        logger.exception(
                            "Write command recovery failed command_id=%s",
                            command.get("command_id"),
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Write command recovery scan failed")

            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_seconds,
                )
            except TimeoutError:
                pass
