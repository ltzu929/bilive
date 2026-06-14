import asyncio
import importlib

import pytest

from src.server.worker_idle import IdleWatchdog, worker_is_busy


def _idle_state():
    return {
        "watcher": {"status": "idle"},
        "lock": {"owner_running": False},
        "pending_tasks": 0,
        "llm": {"status": "idle"},
        "upload": {
            "status": "idle",
            "queue_counts": {
                "queued": 0,
                "uploading": 0,
                "uploaded": 0,
                "publishing": 0,
                "published": 2,
                "failed": 1,
            },
        },
    }


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ({"watcher": {"status": "running"}}, True),
        ({"lock": {"owner_running": True}}, True),
        ({"pending_tasks": 1}, True),
        ({"llm": {"status": "running"}}, True),
        ({"llm": {"status": "occupied"}}, True),
        ({"upload": {"status": "uploading", "queue_counts": {}}}, True),
        ({"upload": {"status": "publishing", "queue_counts": {}}}, True),
        ({"upload": {"status": "idle", "queue_counts": {"queued": 1}}}, True),
        ({"upload": {"status": "idle", "queue_counts": {"uploaded": 1}}}, True),
        ({}, False),
    ],
)
def test_worker_is_busy_blocks_only_real_work(patch, expected):
    state = _idle_state()
    state.update(patch)

    assert worker_is_busy(state) is expected


@pytest.mark.anyio
async def test_idle_watchdog_requests_shutdown_after_full_idle_window():
    now = [0.0]
    shutdowns = []

    async def sleep(_seconds):
        now[0] += 300
        await asyncio.sleep(0)

    watchdog = IdleWatchdog(
        state_reader=_idle_state,
        shutdown_requester=lambda: shutdowns.append(now[0]),
        timeout_seconds=900,
        check_interval_seconds=30,
        monotonic=lambda: now[0],
        sleeper=sleep,
    )

    await watchdog.run()

    assert shutdowns == [900]


@pytest.mark.anyio
async def test_busy_transition_restarts_full_idle_window():
    states = [
        _idle_state(),
        {**_idle_state(), "pending_tasks": 1},
        _idle_state(),
    ]
    now = [0.0]
    shutdowns = []

    def read_state():
        return states.pop(0) if states else _idle_state()

    async def sleep(_seconds):
        now[0] += 450
        await asyncio.sleep(0)

    watchdog = IdleWatchdog(
        state_reader=read_state,
        shutdown_requester=lambda: shutdowns.append(now[0]),
        timeout_seconds=900,
        check_interval_seconds=30,
        monotonic=lambda: now[0],
        sleeper=sleep,
    )

    await watchdog.run()

    assert shutdowns == [1800]


@pytest.mark.anyio
async def test_idle_state_errors_keep_worker_running_for_a_fresh_window():
    calls = [RuntimeError("state unavailable"), _idle_state(), _idle_state()]
    now = [0.0]
    shutdowns = []

    def read_state():
        value = calls.pop(0) if calls else _idle_state()
        if isinstance(value, Exception):
            raise value
        return value

    async def sleep(_seconds):
        now[0] += 450
        await asyncio.sleep(0)

    watchdog = IdleWatchdog(
        state_reader=read_state,
        shutdown_requester=lambda: shutdowns.append(now[0]),
        timeout_seconds=900,
        check_interval_seconds=30,
        monotonic=lambda: now[0],
        sleeper=sleep,
    )

    await watchdog.run()

    assert shutdowns == [1350]


def test_worker_idle_config_uses_environment_overrides(monkeypatch):
    monkeypatch.setenv("BILIVE_WORKER_IDLE_TIMEOUT", "60")
    monkeypatch.setenv("BILIVE_WORKER_IDLE_CHECK_INTERVAL", "5")
    config = importlib.reload(importlib.import_module("src.config.server_config"))

    assert config.WORKER_IDLE_TIMEOUT_SECONDS == 60.0
    assert config.WORKER_IDLE_CHECK_INTERVAL_SECONDS == 5.0

    monkeypatch.delenv("BILIVE_WORKER_IDLE_TIMEOUT")
    monkeypatch.delenv("BILIVE_WORKER_IDLE_CHECK_INTERVAL")
    importlib.reload(config)
    importlib.reload(importlib.import_module("src.config"))
