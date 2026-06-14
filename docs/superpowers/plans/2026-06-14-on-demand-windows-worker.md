# On-Demand Windows Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start the hidden Windows Worker API when the Pi slice page needs it and stop it after 15 minutes of true inactivity without interrupting slicing, LLM, or upload work.

**Architecture:** The Pi wakes an on-demand Windows scheduled task over the existing SSH connection, then continues to use the localhost Worker API through SSH. A focused Windows idle watchdog owns the 15-minute policy, while a Python Uvicorn entrypoint provides hidden startup and graceful lifespan shutdown.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, asyncio, PowerShell Scheduled Tasks, OpenSSH, vanilla JavaScript, pytest.

---

## File Map

- Create `src/server/worker_idle.py`: pure busy-state rules and asynchronous idle watchdog.
- Create `src/server/worker_server.py`: Windows environment setup, file logging, Uvicorn ownership, and graceful shutdown callback.
- Modify `src/server/worker_api.py`: compose runtime state, touch activity, and run/cancel the watchdog in the FastAPI lifespan.
- Modify `src/config/server_config.py`: expose Worker idle timeout settings.
- Modify `src/dashboard/remote_worker.py`: build scheduled-task wake commands and poll Worker readiness.
- Modify `src/dashboard/app.py`: expose explicit wake and use wake-before-dispatch.
- Modify `frontend/app.js`: wake once on page load while keeping status polling side-effect free.
- Modify `frontend/index.html`: bump the JavaScript cache key if needed.
- Modify `start_pipeline.ps1`: retain a manual console launcher through `worker_server`.
- Modify `install_windows_worker_task.ps1`: register a no-trigger `pythonw.exe` task.
- Modify `bilive-server.toml`: add startup and idle timing.
- Modify `README.md`, `docs/architecture.md`, `docs/operations.md`, and `docs/model-runtime.md`: document the on-demand lifecycle.
- Create `tests/test_worker_idle.py` and `tests/test_worker_server.py`.
- Modify `tests/test_worker_api.py`, `tests/test_remote_worker.py`, `tests/test_dashboard_api.py`, `tests/test_dashboard_frontend.py`, and `tests/test_pc_launcher.py`.

### Task 0: Checkpoint the Existing Dashboard Connection Fix

**Files:**
- Existing modifications: `deploy/bilive-dashboard-wrapper.sh`
- Existing modifications: `frontend/app.js`
- Existing modifications: `frontend/index.html`
- Existing modifications: `src/dashboard/task_state.py`
- Existing modifications: `tests/test_dashboard_frontend.py`
- Existing modifications: `tests/test_dashboard_service.py`
- Existing modifications: `tests/test_task_state.py`

- [ ] **Step 1: Re-run the focused regression tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_dashboard_service.py `
  tests\test_dashboard_frontend.py `
  tests\test_task_state.py -q
```

Expected: `30 passed`.

- [ ] **Step 2: Confirm the diff contains only the environment export and terminology fix**

Run:

```powershell
git diff -- `
  deploy/bilive-dashboard-wrapper.sh `
  frontend/app.js `
  frontend/index.html `
  src/dashboard/task_state.py `
  tests/test_dashboard_frontend.py `
  tests/test_dashboard_service.py `
  tests/test_task_state.py
```

Expected: `set -a`/`set +a`, `Windows 重任务节点`, and matching tests only.

- [ ] **Step 3: Commit the verified baseline**

```powershell
git add deploy/bilive-dashboard-wrapper.sh frontend/app.js frontend/index.html `
  src/dashboard/task_state.py tests/test_dashboard_frontend.py `
  tests/test_dashboard_service.py tests/test_task_state.py
git commit -m "fix: connect and clarify Windows worker status"
```

### Task 1: Add Worker Idle Configuration and Policy

**Files:**
- Create: `src/server/worker_idle.py`
- Modify: `src/config/server_config.py`
- Modify: `bilive-server.toml`
- Create: `tests/test_worker_idle.py`

- [ ] **Step 1: Write failing configuration and busy-state tests**

Create `tests/test_worker_idle.py` with:

```python
import asyncio

import pytest

from src.server.worker_idle import IdleWatchdog, worker_is_busy


def idle_state():
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
        (
            {
                "upload": {
                    "status": "idle",
                    "queue_counts": {"queued": 1},
                }
            },
            True,
        ),
        ({}, False),
    ],
)
def test_worker_is_busy_blocks_only_real_work(patch, expected):
    state = idle_state()
    state.update(patch)
    assert worker_is_busy(state) is expected


@pytest.mark.anyio
async def test_idle_watchdog_requests_shutdown_after_full_idle_window():
    now = [0.0]
    shutdowns = []
    watchdog = IdleWatchdog(
        state_reader=idle_state,
        shutdown_requester=lambda: shutdowns.append("stop"),
        timeout_seconds=900,
        check_interval_seconds=30,
        monotonic=lambda: now[0],
        sleeper=lambda _seconds: asyncio.sleep(0),
    )

    task = asyncio.create_task(watchdog.run())
    for value in (899, 900):
        now[0] = value
        await asyncio.sleep(0)
    await task

    assert shutdowns == ["stop"]


@pytest.mark.anyio
async def test_busy_transition_restarts_full_idle_window():
    states = [idle_state(), {**idle_state(), "pending_tasks": 1}, idle_state()]
    now = [0.0]
    shutdowns = []

    def read_state():
        return states.pop(0) if states else idle_state()

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
```

Also add a configuration reload test that sets:

```python
monkeypatch.setenv("BILIVE_WORKER_IDLE_TIMEOUT", "60")
monkeypatch.setenv("BILIVE_WORKER_IDLE_CHECK_INTERVAL", "5")
```

and asserts the reloaded constants are `60.0` and `5.0`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_worker_idle.py -q
```

Expected: import failure for `src.server.worker_idle`.

- [ ] **Step 3: Add configuration**

Add to `bilive-server.toml`:

```toml
[worker]
idle_timeout_seconds = 900
idle_check_interval_seconds = 30
```

In `src/config/server_config.py`, read `worker = config.get("worker", {})` and export:

```python
WORKER_IDLE_TIMEOUT_SECONDS = float(
    os.environ.get(
        "BILIVE_WORKER_IDLE_TIMEOUT",
        worker.get("idle_timeout_seconds", 900),
    )
)
WORKER_IDLE_CHECK_INTERVAL_SECONDS = float(
    os.environ.get(
        "BILIVE_WORKER_IDLE_CHECK_INTERVAL",
        worker.get("idle_check_interval_seconds", 30),
    )
)
```

- [ ] **Step 4: Implement the minimal idle policy**

Create `src/server/worker_idle.py` with:

```python
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
    return any(int(counts.get(name) or 0) > 0 for name in BLOCKING_UPLOAD_COUNTS)


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
```

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_worker_idle.py -q
```

Expected: all idle-policy tests pass.

- [ ] **Step 6: Commit**

```powershell
git add bilive-server.toml src/config/server_config.py `
  src/server/worker_idle.py tests/test_worker_idle.py
git commit -m "feat: add safe worker idle policy"
```

### Task 2: Integrate Graceful Idle Shutdown into the Worker API

**Files:**
- Modify: `src/server/worker_api.py`
- Modify: `tests/test_worker_api.py`

- [ ] **Step 1: Write failing lifespan and activity tests**

Add tests using an injected watchdog factory:

```python
@pytest.mark.anyio
async def test_worker_api_runs_and_cancels_idle_watchdog():
    events = []

    class FakeWatchdog:
        def touch(self):
            events.append("touch")

        async def run(self):
            events.append("run")
            await asyncio.Event().wait()

    app = create_app(
        idle_watchdog_factory=lambda **_kwargs: FakeWatchdog(),
        shutdown_requester=lambda: events.append("shutdown"),
        auto_upload=False,
    )
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert "run" in events

    assert app.state.worker_idle_task.cancelled()


@pytest.mark.anyio
async def test_run_once_and_upload_start_touch_activity():
    touches = []

    class FakeWatchdog:
        def touch(self):
            touches.append("touch")

        async def run(self):
            await asyncio.Event().wait()

    app = create_app(
        worker_starter=lambda: {"status": "started", "pid": 1},
        pending_counter=lambda: 1,
        preflight_reader=lambda: {"ready": True, "checks": {}},
        upload_starter=lambda: {"status": "started", "pid": 2},
        idle_watchdog_factory=lambda **_kwargs: FakeWatchdog(),
        shutdown_requester=lambda: None,
        auto_upload=False,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/worker/run-once")
            await client.post("/api/upload/start")

    assert len(touches) >= 2
```

Add a state-reader test proving upload queue counts come from an injected
`upload_queue_counter`, rather than whether the upload consumer subprocess is
merely alive.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_worker_api.py -q
```

Expected: `create_app()` rejects the new watchdog arguments.

- [ ] **Step 3: Refactor one runtime-state reader**

In `src/server/worker_api.py`, add injected parameters:

```python
shutdown_requester: Callable[[], None] | None = None,
idle_watchdog_factory=None,
idle_timeout_seconds: float | None = None,
idle_check_interval_seconds: float | None = None,
upload_queue_counter: Callable[[], Dict[str, int]] | None = None,
```

Create one nested `read_runtime_state()` that returns:

```python
upload_state = dict(read_upload_status())
upload_state["queue_counts"] = count_upload_queue()
return {
    "status": watcher.get("status", "idle"),
    "watcher": watcher,
    "lock": read_lock_status(),
    "dependencies": read_preflight(),
    "llm": read_llm_status(),
    "pending_tasks": int(count_pending()),
    "upload": upload_state,
}
```

Use `get_upload_queue_counts(db_path)` as the production queue counter.

- [ ] **Step 4: Start and cancel the watchdog in the lifespan**

Build `IdleWatchdog` only when `shutdown_requester` is provided. Store it in
`app.state.worker_idle_watchdog`, create `app.state.worker_idle_task`, and on
shutdown:

```python
task.cancel()
with suppress(asyncio.CancelledError):
    await task
```

Then stop the owned upload consumer through the existing lifespan cleanup.

Call `watchdog.touch()` at the start of `/api/worker/run-once` and
`/api/upload/start`. Do not touch it in either status endpoint.

- [ ] **Step 5: Run Worker API tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_worker_api.py tests\test_worker_idle.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/server/worker_api.py tests/test_worker_api.py
git commit -m "feat: stop idle Windows worker safely"
```

### Task 3: Add the Hidden Python Server and On-Demand Scheduled Task

**Files:**
- Create: `src/server/worker_server.py`
- Create: `tests/test_worker_server.py`
- Modify: `start_pipeline.ps1`
- Modify: `install_windows_worker_task.ps1`
- Modify: `tests/test_pc_launcher.py`

- [ ] **Step 1: Write failing server entrypoint tests**

Create `tests/test_worker_server.py`:

```python
from pathlib import Path

from src.server.worker_server import configure_worker_environment


def test_configure_worker_environment_sets_project_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("BILIVE_DIR", raising=False)
    configure_worker_environment(tmp_path, auto_upload=False)

    assert Path(__import__("os").environ["BILIVE_DIR"]) == tmp_path.resolve()
    assert Path(__import__("os").environ["BILIVE_VIDEOS_DIR"]) == (
        tmp_path / "Videos"
    ).resolve()
    assert __import__("os").environ["BILIVE_AUTO_UPLOAD"] == "0"


def test_shutdown_callback_sets_uvicorn_should_exit():
    from src.server.worker_server import request_server_shutdown

    server = type("Server", (), {"should_exit": False})()
    request_server_shutdown({"server": server})
    assert server.should_exit is True
```

Update `tests/test_pc_launcher.py` to require:

```python
assert "src.server.worker_server" in pipeline_text
assert "src.server.worker_api:api" not in pipeline_text
assert "pythonw.exe" in installer_text
assert "New-ScheduledTaskTrigger -AtLogOn" not in installer_text
assert "-WorkingDirectory" in installer_text
assert "start_pipeline.ps1" not in installer_text
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_worker_server.py tests\test_pc_launcher.py -q
```

Expected: missing `src.server.worker_server` and old launcher assertions fail.

- [ ] **Step 3: Implement `worker_server.py`**

Create a module with:

```python
def configure_worker_environment(project_root: Path, *, auto_upload: bool) -> None:
    root = project_root.resolve()
    os.environ["PYTHONPATH"] = str(root)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    os.environ["BILIVE_DIR"] = str(root)
    os.environ["BILIVE_CONFIG"] = str(root / "bilive-server.toml")
    os.environ["BILIVE_VIDEOS_DIR"] = str(root / "Videos")
    os.environ["BILIVE_DB_PATH"] = str(root / "src" / "db" / "data.db")
    os.environ["BILIVE_COOKIE_FILE"] = str(root / ".secrets" / "bilibili.cookie")
    os.environ["BILIVE_AUTO_UPLOAD"] = "1" if auto_upload else "0"


def request_server_shutdown(holder: dict[str, uvicorn.Server]) -> None:
    server = holder.get("server")
    if server is not None:
        server.should_exit = True
```

`main()` must parse `--no-upload` and `--console`, configure a rotating file
handler under `logs/runtime/worker-api.log`, run `migrate_upload_queue()`, build
the app with the shutdown callback, create `uvicorn.Server`, place it in the
holder, and call `server.run()`.

- [ ] **Step 4: Route the manual PowerShell launcher through the new module**

Keep `start_pipeline.ps1` as the visible diagnostic path:

```powershell
$arguments = @("-m", "src.server.worker_server", "--console")
if ($NoUpload) {
    $arguments += "--no-upload"
}
& $python @arguments
exit $LASTEXITCODE
```

Remove the duplicate Uvicorn and database initialization logic now owned by
`worker_server.py`.

- [ ] **Step 5: Register a no-trigger `pythonw.exe` task**

In `install_windows_worker_task.ps1`:

```powershell
$pythonw = Join-Path $ProjectDir ".venv-win\Scripts\pythonw.exe"
$workerArguments = "-m src.server.worker_server"
if (-not $EnableUpload) {
    $workerArguments += " --no-upload"
}
$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $workerArguments `
    -WorkingDirectory $ProjectDir
```

Remove `New-ScheduledTaskTrigger -AtLogOn` and omit `-Trigger` from
`Register-ScheduledTask`. Retain `MultipleInstances IgnoreNew`, the limited
interactive principal, ownership checks for an existing `2235` listener,
manual `Start-ScheduledTask`, and API verification.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_worker_server.py tests\test_pc_launcher.py `
  tests\test_worker_api.py -q
```

Expected: all launcher and Worker tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/server/worker_server.py tests/test_worker_server.py `
  start_pipeline.ps1 install_windows_worker_task.ps1 `
  tests/test_pc_launcher.py
git commit -m "feat: launch Windows worker on demand"
```

### Task 4: Add Pi-to-Windows Wake and Readiness Polling

**Files:**
- Modify: `src/dashboard/remote_worker.py`
- Modify: `bilive-server.toml`
- Modify: `tests/test_remote_worker.py`

- [ ] **Step 1: Write failing wake tests**

Extend `tests/test_remote_worker.py`:

```python
def test_load_remote_worker_config_builds_scheduled_task_wake(monkeypatch, tmp_path):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "[dashboard.remote_worker]\n"
        "enabled = true\n"
        "timeout = 8\n"
        "startup_timeout = 30\n"
        'task_name = "BiliveWorkerApi"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_WINDOWS_SSH_TARGET", "worker-host")

    config = load_remote_worker_config(config_path)

    assert config.wake_command == [
        "ssh",
        "worker-host",
        "schtasks.exe",
        "/Run",
        "/TN",
        "BiliveWorkerApi",
    ]
    assert config.startup_timeout == 30


def test_wake_remote_worker_starts_task_and_waits_until_ready():
    calls = []
    replies = iter(
        [
            Result(1, "", "connection failed"),
            Result(0, "SUCCESS", ""),
            Result(1, "", "not ready"),
            Result(0, '{"status":"idle","pending_tasks":0}', ""),
        ]
    )

    result = wake_remote_worker(
        configured_remote_worker(),
        runner=lambda command, **kwargs: calls.append(command) or next(replies),
        monotonic=incrementing_clock(),
        sleeper=lambda _seconds: None,
    )

    assert result["status"] == "idle"
    assert calls[1][-4:] == [
        "schtasks.exe",
        "/Run",
        "/TN",
        "BiliveWorkerApi",
    ]


def test_wake_remote_worker_does_not_start_task_when_api_is_ready():
    result = wake_remote_worker(
        configured_remote_worker(),
        runner=lambda command, **_kwargs: Result(
            0, '{"status":"idle","pending_tasks":0}', ""
        ),
    )
    assert result["status"] == "idle"
```

Add a timeout test that asserts `status == "unavailable"` and queued work is
not removed.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_remote_worker.py -q
```

Expected: missing `wake_command`, `startup_timeout`, and
`wake_remote_worker`.

- [ ] **Step 3: Extend `RemoteWorkerConfig`**

Add:

```python
wake_command: list[str] = field(default_factory=list)
startup_timeout: float = 30.0
poll_interval: float = 1.0
```

Read `task_name`, `startup_timeout`, and environment overrides:

```text
BILIVE_WINDOWS_WORKER_TASK
BILIVE_REMOTE_WORKER_STARTUP_TIMEOUT
```

When `BILIVE_WINDOWS_SSH_TARGET` is set, construct the scheduled-task command
shown in Step 1.

- [ ] **Step 4: Implement wake and reuse it before dispatch**

Add:

```python
def wake_remote_worker(
    config: RemoteWorkerConfig | None = None,
    *,
    runner=subprocess.run,
    monotonic=time.monotonic,
    sleeper=time.sleep,
) -> dict[str, Any]:
    ...
```

The function must:

1. Return the current status immediately if it is already available.
2. Run `wake_command` once.
3. Poll only `status_command` until ready or `startup_timeout`.
4. Return sanitized `unavailable` data on start failure or timeout.

Change `trigger_remote_worker()` so positive pending work calls
`wake_remote_worker()` before the existing POST command.

- [ ] **Step 5: Add TOML settings**

Expand the existing section:

```toml
[dashboard.remote_worker]
enabled = true
timeout = 10
startup_timeout = 30
task_name = "BiliveWorkerApi"
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_remote_worker.py -q
```

Expected: all remote wake and trigger tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/dashboard/remote_worker.py tests/test_remote_worker.py `
  bilive-server.toml
git commit -m "feat: wake Windows worker from Pi"
```

### Task 5: Wake Once on Page Entry and Before Work Dispatch

**Files:**
- Modify: `src/dashboard/app.py`
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `tests/test_dashboard_api.py`
- Modify: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Write failing dashboard wake endpoint tests**

Add:

```python
@pytest.mark.anyio
async def test_worker_wake_api_calls_remote_waker(tmp_path, dashboard_client):
    calls = []
    async with dashboard_client(
        tmp_path / "Videos",
        remote_worker_waker=lambda: calls.append("wake")
        or {"status": "idle", "mode": "remote", "enabled": True},
    ) as client:
        response = await client.post("/api/worker-trigger/wake")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert calls == ["wake"]
```

Keep existing slice, requeue, retry-judge, and render tests, but assert they use
the trigger path that now performs wake-before-dispatch.

- [ ] **Step 2: Add failing frontend contract assertions**

In `tests/test_dashboard_frontend.py`, require:

```python
assert 'request("/api/worker-trigger/wake", {' in text
assert "wakeWorkerOnPageLoad()" in text
assert text.count('request("/api/worker-trigger/wake", {') == 1
```

Also keep the existing assertions that each timer calls only
`refreshWorkerStatus()`, proving status polling cannot wake the Worker.

- [ ] **Step 3: Run and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_dashboard_api.py tests\test_dashboard_frontend.py -q
```

Expected: missing `remote_worker_waker`, wake route, and frontend wake call.

- [ ] **Step 4: Add the dashboard endpoint**

Import `wake_remote_worker`, add `remote_worker_waker=None` to `create_app()`,
and create:

```python
def wake_worker() -> Dict[str, Any]:
    if remote_worker_waker is not None:
        return remote_worker_waker()
    return wake_remote_worker()


@app.post("/api/worker-trigger/wake")
async def wake_worker_api() -> Dict[str, Any]:
    return wake_worker()
```

Existing dispatch paths continue through `trigger_remote_worker()`, which now
performs their fallback wake.

- [ ] **Step 5: Wake once during page initialization**

Add:

```javascript
async function wakeWorkerOnPageLoad() {
  if (!elements.workerBadge) return;
  elements.workerBadge.className = "worker-badge worker-running";
  elements.workerBadge.textContent = "Windows 重任务节点：启动中";
  try {
    const status = await request("/api/worker-trigger/wake", {
      method: "POST",
    });
    renderRemoteWorkerStatus(status);
  } catch {
    elements.workerBadge.className = "worker-badge worker-idle";
    elements.workerBadge.textContent = "Windows 重任务节点：离线";
  }
}
```

Call `wakeWorkerOnPageLoad()` once in the startup block. Do not call it from
any interval or `visibilitychange`. Bump the script cache key in
`frontend/index.html`.

- [ ] **Step 6: Run dashboard tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest `
  tests\test_dashboard_api.py tests\test_dashboard_frontend.py `
  tests\test_remote_worker.py -q
```

Expected: all dashboard and wake tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/dashboard/app.py frontend/app.js frontend/index.html `
  tests/test_dashboard_api.py tests/test_dashboard_frontend.py
git commit -m "feat: wake worker when slice page opens"
```

### Task 6: Update Operations Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/model-runtime.md`
- Modify: `tests/test_pc_launcher.py`

- [ ] **Step 1: Write failing documentation contract assertions**

Extend the existing documentation test:

```python
assert "按需启动" in public_docs
assert "15 分钟" in public_docs
assert "pythonw.exe" in public_docs
assert "常驻控制面" not in public_docs
assert "Windows Worker API 常驻" not in public_docs
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_pc_launcher.py -q
```

Expected: documentation assertions fail on the old always-on wording.

- [ ] **Step 3: Update the runtime documentation**

Document these exact operational facts:

- Pi ports `2233` and `2234` remain persistent.
- Windows port `2235` appears only after page entry or task dispatch.
- The scheduled task has no logon trigger.
- The Worker exits after 15 minutes with no pending, running, LLM, or upload
  work.
- `pythonw.exe` prevents a console window.
- `start_pipeline.ps1` remains the manual diagnostic launcher.
- `schtasks /Run /TN BiliveWorkerApi` is the direct recovery command.
- `BILIVE_WORKER_IDLE_TIMEOUT=0` disables automatic exit for diagnostics.

- [ ] **Step 4: Run documentation tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests\test_pc_launcher.py -q
```

Expected: all documentation and launcher contracts pass.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/architecture.md docs/operations.md `
  docs/model-runtime.md tests/test_pc_launcher.py
git commit -m "docs: explain on-demand Windows worker"
```

### Task 7: Full Verification and Dual-Machine Deployment

**Files:**
- No new source files.
- Runtime configuration: `.secrets/env` remains untracked.
- Deployment targets: Windows scheduled task and Pi dashboard service.

- [ ] **Step 1: Run the complete local verification bundle**

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
.\.venv-win\Scripts\python.exe -m compileall -q src
.\.venv-win\Scripts\python.exe -m pip check
git diff --check
```

Expected: all tests pass, compileall exits `0`, pip reports no broken
requirements, and `git diff --check` is empty.

- [ ] **Step 2: Re-register the hidden on-demand Windows task**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install_windows_worker_task.ps1 -EnableUpload
```

Expected: task registration and API verification succeed. Task action points
to `.venv-win\Scripts\pythonw.exe`, has no logon trigger, and no visible
terminal remains.

- [ ] **Step 3: Deploy the Pi dashboard code**

```powershell
ssh pi "cd /mnt/win/bilive && sudo ./deploy/install-bilive-services.sh"
```

Expected: `bilive.service` and `bilive-dashboard.service` are active.

- [ ] **Step 4: Prove status polling is side-effect free**

Stop the Worker task:

```powershell
Stop-ScheduledTask -TaskName BiliveWorkerApi
```

Then request status from Pi:

```powershell
ssh pi "curl -sS http://127.0.0.1:2234/api/worker-trigger/status"
```

Expected: `status=unavailable`; Windows port `2235` remains closed.

- [ ] **Step 5: Prove page wake starts the Worker**

Open `http://192.168.31.157:2234/tasks` in the in-app browser and inspect the
badge.

Expected:

- badge transitions through `Windows 重任务节点：启动中`;
- then reports `空闲` or `处理中`;
- `http://127.0.0.1:2235/api/worker/status` responds on Windows;
- no PowerShell or console window appears.

- [ ] **Step 6: Smoke-test idle shutdown with a temporary short timeout**

Temporarily set:

```powershell
$env:BILIVE_WORKER_IDLE_TIMEOUT = "60"
$env:BILIVE_WORKER_IDLE_CHECK_INTERVAL = "5"
```

Start `pythonw.exe -m src.server.worker_server` in the same environment, keep
all queues empty, and verify port `2235` closes after at least 60 seconds.
Then clear the temporary variables and restart through the scheduled task.

Expected: the smoke instance exits gracefully; the deployed configuration in
`bilive-server.toml` remains `900`.

- [ ] **Step 7: Prove active work blocks shutdown**

Run an idle-policy integration test with a temporary pending marker or action
job, wait longer than the temporary timeout, and confirm port `2235` remains
open. Remove the temporary task, allow one full idle window, and confirm the
port closes.

- [ ] **Step 8: Final runtime checks**

```powershell
ssh pi "systemctl is-active bilive.service bilive-dashboard.service; ss -ltnp | grep -E ':2233|:2234'"
Get-ScheduledTask -TaskName BiliveWorkerApi |
  Select-Object TaskName,State,Triggers,Actions
git status --short
```

Expected:

- Pi recorder and dashboard are active on `2233` and `2234`;
- `BiliveWorkerApi` has no trigger and uses `pythonw.exe`;
- Windows `2235` is allowed to be closed while idle;
- the worktree contains no unintended changes.
