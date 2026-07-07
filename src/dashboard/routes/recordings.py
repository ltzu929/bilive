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
from src.dashboard.eagle_index import build_eagle_source_index


router = APIRouter()


@router.get("/api/rooms")
async def list_rooms(ctx: DashboardContext = Depends(get_context)) -> list[Dict[str, Any]]:
    return [room.to_dict() for room in ctx.store.list_rooms()]


@router.get("/api/slices")
async def list_slices(
    room_id: str | None = None,
    ctx: DashboardContext = Depends(get_context),
) -> list[Dict[str, Any]]:
    try:
        return [item.to_dict() for item in ctx.store.list_slices(room_id)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/tasks")
async def list_tasks(
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
async def list_source_recordings(
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
async def get_source_recording(
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