from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException

from src.server.preflight import run_worker_preflight
from src.server.action_jobs import count_pending_action_jobs
from src.server.upload_control import (
    start_upload_worker,
    stop_upload_worker,
    upload_worker_status,
)
from src.server.worker_control import start_worker_once, worker_status
from src.server.worker_lock import default_worker_lock_path, read_worker_lock


def create_app(
    worker_starter: Callable[[], Dict[str, Any]] | None = None,
    worker_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_starter: Callable[[], Dict[str, Any]] | None = None,
    upload_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_stopper: Callable[[], Dict[str, Any]] | None = None,
    pending_counter: Callable[[], int] | None = None,
    preflight_reader: Callable[[], Dict[str, Any]] | None = None,
    lock_status_reader: Callable[[], Dict[str, Any]] | None = None,
    auto_upload: bool | None = None,
) -> FastAPI:
    start_worker = worker_starter or start_worker_once
    read_worker_status = worker_status_reader or worker_status
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_upload_process = False
        if should_auto_upload:
            try:
                result = start_upload()
                app.state.upload_start_result = result
                owns_upload_process = result.get("status") == "started"
            except (OSError, RuntimeError) as exc:
                app.state.upload_start_error = str(exc)
        try:
            yield
        finally:
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
        watcher = read_worker_status()
        return {
            "status": watcher.get("status", "idle"),
            "watcher": watcher,
            "lock": read_lock_status(),
            "dependencies": read_preflight(),
            "pending_tasks": int(count_pending()),
            "upload": read_upload_status(),
        }

    @app.post("/api/upload/start")
    async def start_upload_consumer() -> Dict[str, Any]:
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
