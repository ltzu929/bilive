# Copyright (c) 2024 bilive.
"""Slice start + worker-trigger control routes.

``/api/slice/start`` is the write-side entry: after starting a scan it triggers
the remote Windows worker, defensively swallowing any worker-trigger failure so
the slice result is still returned to the caller.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context


router = APIRouter()


@router.post("/api/slice/start")
async def start_slice(
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        result = ctx.start_slicing(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pending_tasks = int(result.get("pending_tasks") or result.get("queued") or 0)
    if pending_tasks > 0:
        try:
            result["worker_trigger"] = ctx.trigger_worker(pending_tasks)
        except Exception as exc:  # pragma: no cover - defensive boundary
            result["worker_trigger"] = {
                "status": "failed",
                "message": str(exc),
                "stdout": "",
                "stderr": "",
            }
    return result


@router.get("/api/worker-trigger/status")
async def get_worker_trigger_status(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    return ctx.read_worker_trigger_status()


@router.post("/api/worker-trigger/wake")
async def wake_worker_api(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    return ctx.wake_worker()


@router.post("/api/worker-trigger/stop")
async def stop_worker_api(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    return ctx.stop_worker()