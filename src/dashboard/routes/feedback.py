# Copyright (c) 2024 bilive.
"""Feedback refine routes.

``process_feedback_directory`` is resolved through ``src.dashboard.app`` at
call time so tests can ``monkeypatch.setattr("src.dashboard.app.process_feedback_directory", ...)``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.dashboard._context import DashboardContext, get_context


router = APIRouter()


def _process_feedback_directory(*args: Any, **kwargs: Any):
    # Resolved late via the app module to honor monkeypatch of the app-level name.
    from src.dashboard import app as dashboard_app

    return dashboard_app.process_feedback_directory(*args, **kwargs)


@router.post("/api/refine/preview")
async def refine_preview(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    """Dry-run: count decisions and list what would be generated without writing files."""
    results = _process_feedback_directory(ctx.store.videos_root, enqueue_upload=False, dry_run=True)
    keep_count = sum(1 for r in results if r.decision == "keep")
    review_count = sum(1 for r in results if r.decision == "review")
    drop_count = sum(1 for r in results if r.decision == "drop")

    would_generate = []
    for r in results:
        if r.status == "skipped_decision" or r.status == "missing_slice":
            continue
        would_generate.append({
            "feedback_path": r.feedback_path,
            "decision": r.decision,
            "status": r.status,
            "message": r.message,
        })

    return {
        "keep_count": keep_count,
        "review_count": review_count,
        "drop_count": drop_count,
        "would_generate": would_generate,
    }


@router.post("/api/refine/run")
async def refine_run(ctx: DashboardContext = Depends(get_context)) -> Dict[str, Any]:
    """Execute refinement: generate clips for keep decisions, no upload queue by default."""
    results = _process_feedback_directory(ctx.store.videos_root, enqueue_upload=False)
    keep_count = sum(1 for r in results if r.decision == "keep")
    refined = sum(1 for r in results if r.status == "refined")
    failed = sum(1 for r in results if r.status == "refine_failed")

    return {
        "keep_count": keep_count,
        "refined": refined,
        "failed": failed,
        "upload_queued": False,
    }