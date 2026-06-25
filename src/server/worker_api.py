from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException

from src.db.conn import get_upload_queue_counts
from src.server.preflight import run_worker_preflight
from src.server.action_jobs import count_pending_action_jobs
from src.server.upload_control import (
    start_upload_worker,
    stop_upload_worker,
    upload_worker_status,
)
from src.server.worker_control import start_worker_once, stop_worker, worker_status
from src.server.worker_idle import IdleWatchdog
from src.server.worker_lock import default_worker_lock_path, read_worker_lock


def create_app(
    worker_starter: Callable[[], Dict[str, Any]] | None = None,
    worker_status_reader: Callable[[], Dict[str, Any]] | None = None,
    worker_stopper: Callable[[], Dict[str, Any]] | None = None,
    upload_starter: Callable[[], Dict[str, Any]] | None = None,
    upload_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_stopper: Callable[[], Dict[str, Any]] | None = None,
    pending_counter: Callable[[], int] | None = None,
    preflight_reader: Callable[[], Dict[str, Any]] | None = None,
    lock_status_reader: Callable[[], Dict[str, Any]] | None = None,
    llm_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_queue_counter: Callable[[], Dict[str, int]] | None = None,
    shutdown_requester: Callable[[], None] | None = None,
    idle_watchdog_factory=None,
    idle_timeout_seconds: float | None = None,
    idle_check_interval_seconds: float | None = None,
    auto_upload: bool | None = None,
) -> FastAPI:
    start_worker = worker_starter or start_worker_once
    read_worker_status = worker_status_reader or worker_status
    stop_current_worker = worker_stopper or stop_worker
    start_upload = upload_starter or start_upload_worker
    read_upload_status = upload_status_reader or upload_worker_status
    stop_upload = upload_stopper or stop_upload_worker
    should_auto_upload = _auto_upload_enabled(auto_upload)
    project_root = Path(
        os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2])
    ).resolve()
    videos_root = Path(
        os.environ.get("BILIVE_VIDEOS_DIR", project_root / "Videos")
    ).resolve()
    db_path = Path(
        os.environ.get("BILIVE_DB_PATH", project_root / "src" / "db" / "data.db")
    ).resolve()
    count_upload_queue = upload_queue_counter or (
        lambda: get_upload_queue_counts(db_path)
    )
    count_pending = pending_counter or (
        lambda: (
            len(list(videos_root.rglob("*.mp4.pending")))
            + count_pending_action_jobs(videos_root)
        )
        if videos_root.is_dir()
        else 0
    )
    read_preflight = preflight_reader or (
        lambda: run_worker_preflight(
            project_root=project_root,
            videos_root=videos_root,
            db_path=db_path,
        )
    )
    read_lock_status = lock_status_reader or (
        lambda: read_worker_lock(default_worker_lock_path(project_root))
    )
    if llm_status_reader is None:
        from src.autoslice.mllm_sdk.mimo_video import mimo_status

        read_llm_status = mimo_status
    else:
        read_llm_status = llm_status_reader
    watchdog_factory = idle_watchdog_factory or IdleWatchdog

    def read_activity_state() -> Dict[str, Any]:
        watcher = read_worker_status()
        upload = dict(read_upload_status())
        upload["queue_counts"] = count_upload_queue()
        return {
            "status": watcher.get("status", "idle"),
            "watcher": watcher,
            "lock": read_lock_status(),
            "llm": read_llm_status(),
            "pending_tasks": int(count_pending()),
            "upload": upload,
        }

    def read_runtime_state() -> Dict[str, Any]:
        return {
            **read_activity_state(),
            "dependencies": read_preflight(),
        }

    def touch_activity(app: FastAPI) -> None:
        watchdog = getattr(app.state, "worker_idle_watchdog", None)
        if watchdog is not None:
            watchdog.touch()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_upload_process = False
        watchdog_task = None
        if should_auto_upload:
            try:
                result = start_upload()
                app.state.upload_start_result = result
                owns_upload_process = result.get("status") == "started"
            except (OSError, RuntimeError) as exc:
                app.state.upload_start_error = str(exc)
        if shutdown_requester is not None:
            if idle_timeout_seconds is None or idle_check_interval_seconds is None:
                from src.config.server_config import (
                    WORKER_IDLE_CHECK_INTERVAL_SECONDS,
                    WORKER_IDLE_TIMEOUT_SECONDS,
                )

            watchdog = watchdog_factory(
                state_reader=read_activity_state,
                shutdown_requester=shutdown_requester,
                timeout_seconds=(
                    WORKER_IDLE_TIMEOUT_SECONDS
                    if idle_timeout_seconds is None
                    else idle_timeout_seconds
                ),
                check_interval_seconds=(
                    WORKER_IDLE_CHECK_INTERVAL_SECONDS
                    if idle_check_interval_seconds is None
                    else idle_check_interval_seconds
                ),
            )
            app.state.worker_idle_watchdog = watchdog
            watchdog_task = asyncio.create_task(watchdog.run())
            app.state.worker_idle_task = watchdog_task
        try:
            yield
        finally:
            if watchdog_task is not None and not watchdog_task.done():
                watchdog_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog_task
            if owns_upload_process:
                try:
                    stop_upload()
                except (OSError, RuntimeError):
                    pass

    app = FastAPI(
        title="bilive PC worker",
        version="0.2.0",
        lifespan=lifespan,
    )
    @app.post("/api/worker/run-once")
    async def run_worker_once() -> Dict[str, Any]:
        touch_activity(app)
        pending_tasks = int(count_pending())
        if pending_tasks <= 0:
            return {"status": "no_pending", "pending_tasks": 0}
        dependencies = read_preflight()
        if not dependencies.get("ready"):
            return {
                "status": "dependency_unavailable",
                "pending_tasks": pending_tasks,
                "dependencies": dependencies,
            }
        try:
            result = start_worker()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result.get("status") == "started":
            return {**result, "status": "accepted"}
        return result

    @app.get("/api/worker/status")
    async def get_worker_status() -> Dict[str, Any]:
        return read_runtime_state()

    @app.post("/api/worker/stop")
    async def stop_worker_once() -> Dict[str, Any]:
        touch_activity(app)
        try:
            return stop_current_worker()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/upload/start")
    async def start_upload_consumer() -> Dict[str, Any]:
        touch_activity(app)
        try:
            return start_upload()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/upload/status")
    async def get_upload_status() -> Dict[str, Any]:
        return read_upload_status()

    return app


def _auto_upload_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit

    environment = os.environ.get("BILIVE_AUTO_UPLOAD")
    if environment is not None:
        return environment.strip().lower() not in {"0", "false", "no", "off"}

    from src.config.server_config import UPLOAD_AUTO_START

    return bool(UPLOAD_AUTO_START)


api = create_app()
