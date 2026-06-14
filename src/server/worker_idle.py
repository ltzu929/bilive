from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any


ACTIVE_UPLOAD_STATES = {"uploading", "publishing"}
BLOCKING_UPLOAD_COUNTS = {"queued", "uploading", "uploaded", "publishing"}


def worker_is_busy(state: dict[str, Any]) -> bool:
    if state.get("watcher", {}).get("status") == "running":
        return True
    if bool(state.get("lock", {}).get("owner_running")):
        return True
    if int(state.get("pending_tasks") or 0) > 0:
        return True
    if state.get("llm", {}).get("status") != "idle":
        return True

    upload = state.get("upload", {})
    if upload.get("status") in ACTIVE_UPLOAD_STATES:
        return True
    counts = upload.get("queue_counts", {})
    return any(
        int(counts.get(name) or 0) > 0
        for name in BLOCKING_UPLOAD_COUNTS
    )


class IdleWatchdog:
    def __init__(
        self,
        *,
        state_reader: Callable[[], dict[str, Any]],
        shutdown_requester: Callable[[], None],
        timeout_seconds: float,
        check_interval_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.state_reader = state_reader
        self.shutdown_requester = shutdown_requester
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.check_interval_seconds = max(0.1, float(check_interval_seconds))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._last_activity = monotonic()
        self._logger = logging.getLogger(__name__)

    def touch(self) -> None:
        self._last_activity = self.monotonic()

    async def run(self) -> None:
        if self.timeout_seconds <= 0:
            return
        while True:
            await self.sleeper(self.check_interval_seconds)
            try:
                state = self.state_reader()
            except Exception:
                self._logger.exception("Worker idle-state read failed")
                self.touch()
                continue

            now = self.monotonic()
            if worker_is_busy(state):
                self._last_activity = now
                continue
            if now - self._last_activity < self.timeout_seconds:
                continue

            try:
                confirmed = self.state_reader()
            except Exception:
                self._logger.exception("Worker final idle-state read failed")
                self.touch()
                continue
            if worker_is_busy(confirmed):
                self.touch()
                continue

            self.shutdown_requester()
            return
