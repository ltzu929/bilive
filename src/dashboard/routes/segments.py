# Copyright (c) 2024 bilive.
"""Per-segment action routes (finalize / manual keep / drop / retry / render).

The source workbench helpers are imported lazily inside the handlers so that
loading this module (and therefore the dashboard app) does not pull in
Windows-only heavy dependencies such as ``pysrt`` — the Pi must be able to
import ``src.dashboard.app`` without those installed.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context
from src.dashboard.errors import SegmentStateConflict
from src.server.action_jobs import SegmentActionConflict


router = APIRouter()


def _segment_action(action) -> Dict[str, Any]:
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SegmentActionConflict, SegmentStateConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _workbench():
    from src.dashboard import source_workbench

    return source_workbench


def _ensure_segment_idle(ctx: DashboardContext, segment_id: str) -> None:
    active = ctx.active_segment_job(segment_id)
    if active is not None:
        raise SegmentActionConflict(
            f"segment already has active action: {active.get('action')}"
        )


@router.post("/api/segments/{segment_id}/manual-keep")
async def segment_manual_keep(
    segment_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(
        lambda: (
            _ensure_segment_idle(ctx, segment_id),
            wb.manual_keep_segment(ctx.store.videos_root, segment_id, payload),
        )[1]
    )


@router.post("/api/segments/{segment_id}/finalize")
async def segment_finalize(
    segment_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    """Persist review edits and queue canonical Windows-only finalization."""
    wb = _workbench()

    def prepare_and_queue() -> Dict[str, Any]:
        normalized_payload = wb.validate_segment_finalize_payload(payload)
        _ensure_segment_idle(ctx, segment_id)
        prepared = wb.prepare_segment_finalize(
            ctx.store.videos_root,
            segment_id,
            normalized_payload,
        )
        job_payload = {
            "title": str(prepared.get("title") or ""),
            "description": str(prepared.get("description") or ""),
            "tags": list(prepared.get("tags") or []),
            "start_seconds": float(prepared.get("start_seconds") or 0),
            "end_seconds": float(prepared.get("end_seconds") or 0),
            "subtitle_style": dict(prepared.get("subtitle_style") or {}),
            "_expected_revision": int(prepared.get("revision") or 0),
        }
        queued_segment: dict[str, Any] = {}

        def record_pending(result: Dict[str, Any]) -> None:
            queued_segment["value"] = wb.record_segment_action_state(
                ctx.store.videos_root,
                segment_id,
                status="pending",
                job_id=result["job_id"],
            )

        result = ctx.queue_segment_action(
            "finalize_segment",
            segment_id,
            payload=job_payload,
            after_enqueue=record_pending,
        )
        result["segment"] = queued_segment["value"]
        return result

    return _segment_action(prepare_and_queue)


@router.post("/api/segments/{segment_id}/approve-publish")
async def segment_approve_publish(
    segment_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    """Activate a staged final artifact after the second human confirmation."""
    wb = _workbench()
    return _segment_action(
        lambda: (
            _ensure_segment_idle(ctx, segment_id),
            wb.approve_publish_segment(ctx.store.videos_root, segment_id),
        )[1]
    )


@router.post("/api/segments/{segment_id}/drop")
async def segment_drop(
    segment_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(
        lambda: (
            _ensure_segment_idle(ctx, segment_id),
            wb.drop_segment(ctx.store.videos_root, segment_id, payload),
        )[1]
    )


@router.post("/api/segments/{segment_id}/range")
async def segment_range(
    segment_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    wb = _workbench()
    return _segment_action(
        lambda: (
            _ensure_segment_idle(ctx, segment_id),
            wb.update_segment_range(ctx.store.videos_root, segment_id, payload),
        )[1]
    )


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
        lambda: (
            _ensure_segment_idle(ctx, segment_id),
            wb.update_segment_subtitle_style(
                ctx.store.videos_root,
                segment_id,
                payload,
            ),
        )[1]
    )


@router.post("/api/segments/{segment_id}/reburn")
async def segment_reburn(
    segment_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _segment_action(lambda: ctx.queue_segment_action("reburn_subtitles", segment_id))
