from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.server.upload_control import (
    start_upload_worker,
    stop_upload_worker,
    upload_worker_status,
)
from src.server.worker_control import start_worker_once, worker_status


def create_app(
    worker_starter: Callable[[], Dict[str, Any]] | None = None,
    worker_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_starter: Callable[[], Dict[str, Any]] | None = None,
    upload_status_reader: Callable[[], Dict[str, Any]] | None = None,
    upload_stopper: Callable[[], Dict[str, Any]] | None = None,
    auto_upload: bool | None = None,
) -> FastAPI:
    start_worker = worker_starter or start_worker_once
    read_worker_status = worker_status_reader or worker_status
    start_upload = upload_starter or start_upload_worker
    read_upload_status = upload_status_reader or upload_worker_status
    stop_upload = upload_stopper or stop_upload_worker
    should_auto_upload = _auto_upload_enabled(auto_upload)

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_private_network_access_header(request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    @app.post("/api/worker/run-once")
    async def run_worker_once() -> Dict[str, Any]:
        try:
            return start_worker()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/worker/status")
    async def get_worker_status() -> Dict[str, Any]:
        return read_worker_status()

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
