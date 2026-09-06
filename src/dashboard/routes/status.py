# Copyright (c) 2024 bilive.
"""Read-only upload dashboard + feedback routes.

``read_upload_dashboard`` / ``read_dashboard_settings`` are resolved through
``src.dashboard.app`` at call time so tests that monkeypatch those app-level
names still take effect. The slice feedback PATCH uses the per-app store via
the standard context dependency.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context


router = APIRouter()


@router.get("/api/upload-dashboard")
def get_upload_dashboard(status: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    from src.dashboard import app as dashboard_app

    if not status and limit == 50 and offset == 0:
        return dashboard_app.read_upload_dashboard()
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(status_code=400, detail="Invalid page")
    return dashboard_app.read_upload_dashboard(status=status, limit=limit, offset=offset)


@router.get("/api/dashboard-settings")
def get_dashboard_settings() -> Dict[str, Any]:
    from src.dashboard import app as dashboard_app

    return dashboard_app.read_dashboard_settings()


@router.patch("/api/slices/{slice_id}/feedback")
def update_feedback(
    slice_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        return ctx.store.write_feedback(slice_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/api/uploads/{item_id}/retry")
def retry_upload(item_id: int, ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    from src.db.conn import connect_readonly
    from src.server.action_jobs import enqueue_action_job, SegmentActionConflict
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid upload id")
    with connect_readonly() as db:
        row = db.execute("select * from upload_queue where id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload item not found")
    if row["status"] != "failed" or row["remote_filename"]:
        raise HTTPException(status_code=409, detail="请先核对上传或投稿结果，未重试")
    try:
        result = enqueue_action_job(ctx.store.videos_root, action="retry_upload",
                                    recording_id=f"upload-{item_id}", payload={"upload_id": item_id})
    except SegmentActionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result["job_id"] = result["job"]["job_id"]
    try:
        result["worker_trigger"] = ctx.trigger_worker(1)
    except Exception as exc:
        result["worker_trigger"] = {"status": "unavailable", "message": str(exc)}
    return result
