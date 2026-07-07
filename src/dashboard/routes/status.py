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
async def get_upload_dashboard() -> Dict[str, Any]:
    from src.dashboard import app as dashboard_app

    return dashboard_app.read_upload_dashboard()


@router.get("/api/dashboard-settings")
async def get_dashboard_settings() -> Dict[str, Any]:
    from src.dashboard import app as dashboard_app

    return dashboard_app.read_dashboard_settings()


@router.patch("/api/slices/{slice_id}/feedback")
async def update_feedback(
    slice_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    try:
        return ctx.store.write_feedback(slice_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc