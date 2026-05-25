from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.server.worker_control import start_worker_once, worker_status


def create_app(
    worker_starter: Callable[[], Dict[str, Any]] | None = None,
    worker_status_reader: Callable[[], Dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="bilive PC worker", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    start_worker = worker_starter or start_worker_once
    read_worker_status = worker_status_reader or worker_status

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

    return app


api = create_app()
