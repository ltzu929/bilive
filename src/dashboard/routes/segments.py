# Copyright (c) 2024 bilive.
"""Per-segment action routes (manual keep / drop / range / retry / render).

The source workbench helpers are imported lazily inside the handlers so that
loading this module (and therefore the dashboard app) does not pull in
Windows-only heavy dependencies such as ``pysrt`` — the Pi must be able to
import ``src.dashboard.app`` without those installed.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context


router = APIRouter()


def _segment_action(action) -> Dict[str, Any]:
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _workbench():
    from src.dashboard import source_workbench

    return source_workbench


@router.post("/api/segments/{segment_id}/manual-keep")
async def segment_manual_keep(
    segment_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(
        lambda: wb.manual_keep_segment(ctx.store.videos_root, segment_id, payload)
    )


@router.post("/api/segments/{segment_id}/drop")
async def segment_drop(
    segment_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(lambda: wb.drop_segment(ctx.store.videos_root, segment_id, payload))


@router.post("/api/segments/{segment_id}/range")
async def segment_range(
    segment_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(lambda: wb.update_segment_range(ctx.store.videos_root, segment_id, payload))


@router.post("/api/segments/{segment_id}/retry-judge")
async def segment_retry_judge(
    segment_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _segment_action(lambda: ctx.queue_segment_action("retry_judge", segment_id))


@router.post("/api/segments/{segment_id}/render")
async def segment_render(
    segment_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _segment_action(lambda: ctx.queue_segment_action("render_segment", segment_id))


@router.post("/api/segments/{segment_id}/subtitle-style")
async def segment_subtitle_style(
    segment_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(
        lambda: wb.update_segment_subtitle_style(ctx.store.videos_root, segment_id, payload)
    )


@router.post("/api/segments/{segment_id}/reburn")
async def segment_reburn(
    segment_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _segment_action(lambda: ctx.queue_segment_action("reburn_subtitles", segment_id))