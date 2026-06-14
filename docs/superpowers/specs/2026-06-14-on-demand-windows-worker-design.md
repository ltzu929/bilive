# On-Demand Windows Worker Design

## Goal

Run the Windows Worker API only when the Pi-hosted slice page needs it, hide
its console window, and stop it after 15 continuous minutes without slicing,
LLM, or upload work.

## Boundaries

- The slice dashboard remains on the Pi at port `2234`.
- Windows continues to own slicing, ASR, LLM judging, subtitle rendering, and
  upload work.
- Opening `/tasks` sends one explicit wake request. Periodic status polling
  does not extend the Worker lifetime or restart an idle Worker.
- Clicking an action that needs Windows work also wakes the Worker before
  dispatching the action.
- A page that remains open does not keep an otherwise idle Worker alive.
- Closing the Worker API does not affect the Pi recorder or dashboard.
- The managed llama.cpp process keeps its existing per-batch lifecycle and is
  unloaded before the Worker can be considered idle.

## Wake Path

The Pi must be able to start the Worker while port `2235` is closed, so wake-up
cannot depend on the Worker HTTP API.

The dashboard uses its existing SSH connection to Windows and runs:

```text
schtasks.exe /Run /TN BiliveWorkerApi
```

The `BiliveWorkerApi` scheduled task becomes an on-demand task with no logon
trigger. Its single-instance policy remains `IgnoreNew`, so repeated page loads
or concurrent actions do not create duplicate Worker processes.

After starting the task, the Pi polls the existing Worker status command until
port `2235` responds or the configured startup timeout expires. A timeout is
reported to the page as an unavailable Windows heavy-task node; pending markers
and manual action jobs remain intact.

The dashboard exposes:

```text
POST /api/worker-trigger/wake
```

The frontend calls this endpoint once during page initialization. Existing
slice, requeue, retry-judge, and render paths use the same wake-before-dispatch
operation as a fallback.

## Hidden Windows Process

The scheduled task launches `.venv-win\Scripts\pythonw.exe` directly instead of
opening `powershell.exe` in an interactive console. A new Python server
entrypoint sets the same project environment currently prepared by
`start_pipeline.ps1`, initializes the upload database, configures file logging,
and runs `uvicorn.Server`.

The server entrypoint owns the Uvicorn server object. This gives the Worker API
a graceful shutdown callback that sets `server.should_exit = True`, allowing
the FastAPI lifespan cleanup to stop the upload consumer before the process
exits.

`start_pipeline.ps1` remains a manual diagnostic entrypoint. It calls the same
Python server entrypoint but can still show logs when deliberately started in a
terminal.

## Idle Shutdown

The Worker API starts an asynchronous watchdog during its lifespan. The default
idle timeout is `900` seconds and the check interval is `30` seconds.

The activity timestamp is reset when:

- the Worker API starts;
- `/api/worker/run-once` accepts or observes work;
- the upload consumer is explicitly started.

Status requests do not reset activity.

The watchdog requests graceful shutdown only when all conditions remain true:

- the inactivity duration is at least 15 minutes;
- the one-shot watcher reports `idle`;
- the worker lock has no live owner;
- there are no pending `.mp4.pending` files or action jobs;
- the managed LLM status is `idle`;
- the upload queue has no `queued`, `uploading`, `uploaded`, or `publishing`
  items;
- the upload runtime status is not actively uploading or publishing.

`failed` and `published` upload rows do not keep the Worker alive. A
`paused_auth` upload remains queued and therefore blocks shutdown until it is
resolved or explicitly failed.

Once work finishes, the activity timestamp is refreshed at the transition to
fully idle. This guarantees a full 15-minute idle window after the last real
task, even if that task ran longer than 15 minutes.

## Configuration

`bilive-server.toml` gains:

```toml
[dashboard.remote_worker]
enabled = true
timeout = 10
startup_timeout = 30
task_name = "BiliveWorkerApi"

[worker]
idle_timeout_seconds = 900
idle_check_interval_seconds = 30
```

Environment overrides remain available for deployment:

```text
BILIVE_WINDOWS_WORKER_TASK
BILIVE_REMOTE_WORKER_STARTUP_TIMEOUT
BILIVE_WORKER_IDLE_TIMEOUT
BILIVE_WORKER_IDLE_CHECK_INTERVAL
```

Setting the idle timeout to `0` disables automatic shutdown for diagnostics.

## Components

`src/dashboard/remote_worker.py`

- Builds the SSH scheduled-task wake command.
- Starts the Worker only when status is unavailable.
- Polls readiness and then executes the requested Worker API call.
- Keeps status reads side-effect free.

`src/dashboard/app.py`

- Adds the explicit wake endpoint.
- Uses wake-before-dispatch for all operations that enqueue Windows work.

`frontend/app.js`

- Sends one wake request when the slice page initializes.
- Shows `启动中`, `空闲`, `处理中`, or `离线` without waking on status polls.

`src/server/worker_idle.py`

- Contains the independently testable idle-state decision and watchdog loop.
- Treats upload queue state separately from the always-running upload consumer
  process.

`src/server/worker_server.py`

- Prepares the Windows environment and database.
- Runs Uvicorn without requiring PowerShell.
- Provides the graceful shutdown callback used by the idle watchdog.

`install_windows_worker_task.ps1`

- Registers an on-demand, single-instance task with no logon trigger.
- Uses `pythonw.exe` and the project working directory.
- Verifies manual task start and port `2235`, then leaves the task running for
  the normal idle timeout.

## Failure Handling

- Windows is off or SSH fails: the Pi dashboard stays available and reports the
  Windows node as offline.
- Scheduled task start fails: the wake endpoint returns the sanitized command
  error without deleting queued work.
- Worker startup times out: pending tasks remain queued for a later retry.
- Idle checks raise an exception: the watchdog logs the error and keeps the
  Worker running rather than risking an unsafe shutdown.
- Worker or upload work starts during a shutdown check: the final state check
  cancels shutdown and resets the idle window.
- Graceful shutdown runs FastAPI lifespan cleanup and stops only processes
  owned by the Worker API.

## Verification

- Unit tests cover wake command construction, unavailable-to-ready polling,
  no-op wake when already running, timeout behavior, and side-effect-free
  status reads.
- Dashboard API tests cover page wake and wake-before-dispatch.
- Frontend contract tests cover one startup wake call and prove periodic status
  polling does not call the wake endpoint.
- Idle-policy tests cover every blocking state and the full 15-minute
  transition.
- Worker API lifespan tests prove watchdog startup, graceful exit request, and
  upload cleanup.
- PowerShell contract tests prove the scheduled task has no logon trigger and
  launches `pythonw.exe`.
- Live verification confirms opening the Pi page starts port `2235`, no console
  window appears, active tasks prevent shutdown, and 15 minutes of true idle
  closes port `2235`.
