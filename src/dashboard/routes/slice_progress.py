# Copyright (c) 2024 bilive.
"""Slice progress + diagnostics routes (read-only slice status)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.dashboard._context import DashboardContext, get_context
from src.dashboard.slice_control import load_pending_queue_state
from src.burn.slice_progress import load_progress_state
from src.dashboard._helpers import (
    build_queued_progress,
    build_slice_diagnostics,
    enrich_slice_progress,
)


router = APIRouter()


@router.get("/api/slice-progress")
def get_slice_progress(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    progress = load_progress_state()
    queue_state = load_pending_queue_state(ctx.store.videos_root)
    if queue_state["pending_tasks"] and (
        progress["status"] == "idle" or progress.get("stale")
    ):
        progress = build_queued_progress(queue_state)
    else:
        progress.update(queue_state)
    return enrich_slice_progress(progress, ctx.store)


@router.get("/api/slice-diagnostics")
def get_slice_diagnostics(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    progress = load_progress_state()
    queue_state = load_pending_queue_state(ctx.store.videos_root)
    return build_slice_diagnostics(progress, queue_state)


@router.get("/api/slice-dashboard")
def get_slice_dashboard(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    # Resolved through the app module so tests can monkeypatch
    # src.dashboard.app.read_slice_dashboard by dotted path.
    from src.dashboard import app as dashboard_app

    return dashboard_app.read_slice_dashboard(ctx.store.videos_root)

@router.get("/api/review-status")
def get_review_status(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    import time
    progress = load_progress_state()
    queue = load_pending_queue_state(ctx.store.videos_root)
    diagnostics = build_slice_diagnostics(dict(progress), queue)
    if queue["pending_tasks"] and (progress["status"] == "idle" or progress.get("stale")):
        progress = build_queued_progress(queue)
    else:
        progress.update(queue)
    return {"sampled_at": time.time(), "progress": enrich_slice_progress(progress, ctx.store),
            "diagnostics": diagnostics, "worker": ctx.read_worker_trigger_status()}
