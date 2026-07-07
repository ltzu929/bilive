# Copyright (c) 2024 bilive.
"""Task lifecycle routes: requeue / cancel-pending / mark-done + action jobs lookup."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context
from src.dashboard.task_state import (
    cancel_pending_task,
    mark_done_task,
    requeue_task,
)
from src.server.action_jobs import read_action_job


router = APIRouter()


@router.get("/api/jobs/{job_id}")
async def get_action_job(
    job_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        return read_action_job(ctx.store.videos_root, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/requeue")
async def task_requeue(
    task_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        result = requeue_task(ctx.store.videos_root, task_id)
        result["worker_trigger"] = ctx.trigger_worker(1)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/cancel-pending")
async def task_cancel_pending(
    task_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        return cancel_pending_task(ctx.store.videos_root, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/mark-done")
async def task_mark_done(
    task_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        return mark_done_task(ctx.store.videos_root, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc