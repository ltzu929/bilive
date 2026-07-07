# Copyright (c) 2024 bilive.
"""Bilive dashboard FastAPI app factory.

Route handlers live in :mod:`src.dashboard.routes.*` and share per-app state
through a :class:`~src.dashboard._context.DashboardContext` stored on
``app.state.ctx``. The ``process_feedback_directory`` / ``read_upload_dashboard``
/ ``read_dashboard_settings`` names are kept re-exported at module scope so tests
that monkeypatch them by dotted path (``"src.dashboard.app.<name>"``) still
work — route modules resolve those names back through this module at call time.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.dashboard._context import DashboardContext
from src.dashboard._helpers import (
    default_videos_root,
    media_response,
    process_feedback_directory,
    read_dashboard_settings,
    read_slice_dashboard,
    read_upload_dashboard,
    upload_path_parts,
)
from src.dashboard.file_store import DashboardFileStore
from src.dashboard.routes import (
    feedback as feedback_routes,
    media as media_routes,
    recordings as recordings_routes,
    segments as segments_routes,
    slice_control as slice_control_routes,
    slice_progress as slice_progress_routes,
    status as status_routes,
    tasks as tasks_routes,
)


# Re-exports kept here for back-compat (tests monkeypatch these dotted paths
# and import some directly). Keep this block in sync with re-exported names.
__all__ = [
    "create_app",
    "media_response",
    "upload_path_parts",
    "read_dashboard_settings",
    "read_upload_dashboard",
    "read_slice_dashboard",
    "process_feedback_directory",
    "api",
]


def create_app(
    videos_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    slice_starter=None,
    remote_worker_trigger=None,
    remote_worker_status_reader=None,
    remote_worker_waker=None,
    remote_worker_stopper=None,
) -> FastAPI:
    app = FastAPI(title="bilive dashboard", version="0.1.0")
    store = DashboardFileStore(videos_root or default_videos_root())
    app.state.ctx = DashboardContext(
        store=store,
        slice_starter=slice_starter,
        remote_worker_trigger=remote_worker_trigger,
        remote_worker_status_reader=remote_worker_status_reader,
        remote_worker_waker=remote_worker_waker,
        remote_worker_stopper=remote_worker_stopper,
    )

    @app.middleware("http")
    async def validate_lan_request(request: Request, call_next):
        raw_host = request.headers.get("host", "").lower()
        try:
            host = (urlsplit(f"//{raw_host}").hostname or "").lower()
        except ValueError:
            host = ""
        configured = {
            value.strip().lower()
            for value in os.environ.get("BILIVE_DASHBOARD_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        }
        host_allowed = host in {"localhost", "test"} or host in configured
        if not host_allowed:
            try:
                host_allowed = ipaddress.ip_address(host).is_private
            except ValueError:
                host_allowed = False
        if not host_allowed:
            return JSONResponse({"detail": "Invalid dashboard host"}, status_code=400)

        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin_host = urlsplit(origin).netloc.lower()
            request_host = request.headers.get("host", "").lower()
            if origin_host != request_host:
                return JSONResponse(
                    {"detail": "Cross-origin dashboard write rejected"},
                    status_code=403,
                )
        return await call_next(request)

    app.include_router(recordings_routes.router)
    app.include_router(segments_routes.router)
    app.include_router(tasks_routes.router)
    app.include_router(status_routes.router)
    app.include_router(slice_progress_routes.router)
    app.include_router(slice_control_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(media_routes.router)

    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            index_path = static_path / "index.html"

            if index_path.is_file():

                from fastapi.responses import FileResponse

                @app.get("/tasks", include_in_schema=False)
                @app.get("/uploads", include_in_schema=False)
                @app.get("/settings", include_in_schema=False)
                async def workspace_page() -> FileResponse:
                    return FileResponse(index_path)

            app.mount("/", StaticFiles(directory=static_path, html=True), name="web")

    return app


api = create_app(
    static_dir=os.environ.get(
        "BILIVE_DASHBOARD_STATIC",
        str(Path(__file__).resolve().parents[2] / "frontend"),
    )
)