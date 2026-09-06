# Copyright (c) 2024 bilive.
"""Read-only recording listing routes.

The source workbench helpers are imported lazily inside the handlers so that
loading this module (and therefore the dashboard app) does not pull in
Windows-only heavy dependencies such as ``pysrt`` — the Pi must be able to
import ``src.dashboard.app`` without those installed.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.dashboard._context import DashboardContext, get_context
from src.dashboard.errors import SegmentStateConflict
from src.dashboard.eagle_index import build_eagle_source_index
from src.dashboard.source_lifecycle import (
    RecordingStateConflict,
    read_recording_state,
    set_review_state,
    set_trash_job_state,
)
from src.server.action_jobs import action_submission_lock
from src.dashboard.task_state import resolve_task_id
from src.server.action_jobs import SegmentActionConflict


router = APIRouter()


def _recording_action(ctx, action) -> Dict[str, Any]:
    try:
        with action_submission_lock(ctx.store.videos_root):
            result = action()
        queued = result.get("trash_job", result)
        if queued.get("job_id") and queued.get("status") == "accepted":
            try:
                queued["worker_trigger"] = ctx.trigger_worker(1)
            except Exception as exc:
                queued["worker_trigger"] = {"status": "unavailable", "message": str(exc)}
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SegmentActionConflict, SegmentStateConflict, RecordingStateConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _workbench():
    from src.dashboard import source_workbench

    return source_workbench


def _recording_source(ctx: DashboardContext, task_id: str):
    source = resolve_task_id(ctx.store.videos_root, task_id)
    return source, source.relative_to(ctx.store.videos_root).as_posix(), source.parent.name


def _queue_trash(ctx: DashboardContext, task_id: str) -> Dict[str, Any]:
    state = read_recording_state(ctx.store.videos_root, task_id) or {}
    if str(state.get("trash_status") or "") == "done":
        return {
            "status": "already_trashed",
            "task_id": task_id,
            "review_state": str(state.get("review_state") or "trash_pending"),
            "trash_job_id": str(state.get("trash_job_id") or ""),
        }
    if state.get("trash_plan"):
        source_rel_path = str(state["trash_plan"]["source_rel_path"])
        room_id = str(state.get("room_id") or "")
    else:
        source, source_rel_path, room_id = _recording_source(ctx, task_id)

    def mark_pending(result: Dict[str, Any]) -> None:
        set_review_state(
            ctx.store.videos_root,
            task_id,
            "trash_pending",
            source_rel_path=source_rel_path,
            room_id=room_id,
        )
        set_trash_job_state(
            ctx.store.videos_root,
            task_id,
            status="pending",
            job_id=str(result.get("job_id") or ""),
        )

    result = ctx.queue_recording_action(
        "trash_recording",
        task_id,
        after_enqueue=mark_pending,
        wake=False,
    )
    result["task_id"] = task_id
    result["review_state"] = "trash_pending"
    return result


@router.get("/api/rooms")
def list_rooms(ctx: DashboardContext = Depends(get_context)) -> list[Dict[str, Any]]:
    return [room.to_dict() for room in ctx.store.list_rooms()]


@router.get("/api/slices")
def list_slices(
    room_id: str | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> list[Dict[str, Any]]:
    try:
        return [item.to_dict() for item in ctx.store.list_slices(room_id)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/tasks")
def list_tasks(
    room_id: str | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> list[Dict[str, Any]]:
    from src.dashboard.task_state import build_task_inventory

    room_names = {room.room_id: room.name for room in ctx.store.list_rooms()}
    tasks = build_task_inventory(ctx.store.videos_root, room_id=room_id)
    for task in tasks:
        task["room_name"] = room_names.get(task["room_id"], task["room_id"])
    return tasks


@router.get("/api/source-recordings")
def list_source_recordings(
    room_id: str | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> list[Dict[str, Any]]:
    from src.dashboard.source_workbench import build_source_recording_list

    room_names = {room.room_id: room.name for room in ctx.store.list_rooms()}
    return build_source_recording_list(
        ctx.store.videos_root,
        room_names=room_names,
        room_id=room_id,
    )


@router.get("/api/source-recordings/{task_id}")
def get_source_recording(
    task_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    from src.dashboard.source_workbench import build_source_recording_detail

    room_names = {room.room_id: room.name for room in ctx.store.list_rooms()}
    try:
        return build_source_recording_detail(
            ctx.store.videos_root,
            task_id,
            room_names=room_names,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/source-recordings/{task_id}/missed-segments")
def create_missed_segment(
    task_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    """Persist a manually marked interval and queue Windows-only rendering."""
    wb = _workbench()

    def prepare_and_queue() -> Dict[str, Any]:
        prepared = wb.prepare_missed_segment(
            ctx.store.videos_root,
            task_id,
            payload,
        )
        segment_id = str(prepared.get("segment_id") or "")
        pending_segment: dict[str, Any] = {}

        def record_pending(result: Dict[str, Any]) -> None:
            pending_segment["value"] = wb.record_segment_action_state(
                ctx.store.videos_root,
                segment_id,
                status="pending",
                job_id=str(result.get("job_id") or ""),
                action="create_missed_segment",
            )

        result = ctx.queue_segment_action(
            "create_missed_segment",
            segment_id,
            after_enqueue=record_pending,
            wake=False,
        )
        result["task_id"] = task_id
        result["segment"] = pending_segment["value"]
        return result

    return _recording_action(ctx, prepare_and_queue)


@router.post("/api/source-recordings/{task_id}/review-complete")
def complete_source_review(
    task_id: str,
    payload: Dict[str, Any] | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    """Close human review and enqueue the independent source cleanup job."""
    wb = _workbench()

    def complete_and_queue() -> Dict[str, Any]:
        state = read_recording_state(ctx.store.videos_root, task_id) or {}
        if str(state.get("trash_status") or "") == "done":
            return {
                "task_id": task_id,
                "review_state": str(state.get("review_state") or "trash_pending"),
                "trash_status": "done",
                "trash_job_id": str(state.get("trash_job_id") or ""),
            }
        active = ctx.active_recording_job(task_id)
        if active is not None and str(state.get("review_state") or "") == "trash_pending":
            return {
                "task_id": task_id,
                "review_state": "trash_pending",
                "trash_job": active,
                "job_id": str(active.get("job_id") or ""),
                "status": "already_pending",
            }
        data = payload if isinstance(payload, dict) else {}
        prepared = wb.prepare_source_review_completion(
            ctx.store.videos_root,
            task_id,
            confirmed_no_content=data.get("confirmed_no_content") is True,
        )
        trash = _queue_trash(ctx, task_id)
        prepared["trash_job"] = trash
        prepared["review_state"] = "trash_pending"
        return prepared

    return _recording_action(ctx, complete_and_queue)


@router.post("/api/source-recordings/{task_id}/trash")
def trash_source_recording(
    task_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    """Queue source-package recycling after the recording review is closed."""

    def queue() -> Dict[str, Any]:
        state = read_recording_state(ctx.store.videos_root, task_id) or {}
        if str(state.get("review_state") or "") not in {
            "review_complete",
            "trash_pending",
        }:
            raise RecordingStateConflict("尚未完成整场复核，不能回收源录播")
        return _queue_trash(ctx, task_id)

    return _recording_action(ctx, queue)


@router.get("/api/eagle/source-recordings")
def list_eagle_source_recordings(
    room_id: str | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> JSONResponse:
    room_names = {room.room_id: room.name for room in ctx.store.list_rooms()}
    return JSONResponse(
        build_eagle_source_index(
            ctx.store.videos_root,
            room_names=room_names,
            room_id=room_id,
        ),
    )
