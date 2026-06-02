# Copyright (c) 2024 bilive.

import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.dashboard.file_store import DashboardFileStore
from src.dashboard.slice_control import load_pending_queue_state, start_slice_scan
from src.dashboard.task_state import (
    build_task_inventory,
    cancel_pending_task,
    mark_done_task,
    requeue_task,
)
from src.burn.slice_progress import load_progress_state
from src.burn.feedback_refine import process_feedback_directory


CHUNK_SIZE = 1024 * 1024


def default_videos_root() -> Path:
    env_path = os.environ.get("BILIVE_VIDEOS_DIR")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "Videos"


def iter_file_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes=") or "," in range_header:
        raise ValueError("Unsupported range")
    start_text, separator, end_text = range_header[6:].partition("-")
    if not separator:
        raise ValueError("Unsupported range")

    if start_text == "":
        suffix_size = int(end_text)
        if suffix_size <= 0:
            raise ValueError("Invalid range")
        start = max(file_size - suffix_size, 0)
        end = file_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1

    if start < 0 or start >= file_size or end < start:
        raise ValueError("Invalid range")
    return start, min(end, file_size - 1)


def media_response(
    path: Path,
    request: Request,
    media_type: str | None = None,
) -> Response:
    file_size = path.stat().st_size
    response_media_type = media_type or mimetypes.guess_type(path.name)[0]
    response_media_type = response_media_type or "application/octet-stream"
    range_header = request.headers.get("range")
    common_headers = {"Accept-Ranges": "bytes"}

    if not range_header:
        return FileResponse(
            path,
            media_type=response_media_type,
            headers=common_headers,
        )

    try:
        start, end = parse_range_header(range_header, file_size)
    except (TypeError, ValueError):
        return Response(
            status_code=416,
            headers={
                **common_headers,
                "Content-Range": f"bytes */{file_size}",
            },
        )

    content_length = end - start + 1
    headers = {
        **common_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    with path.open("rb") as file:
        file.seek(start)
        content = file.read(content_length)
    return Response(
        content,
        status_code=206,
        media_type=response_media_type,
        headers=headers,
    )


def create_app(
    videos_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    slice_starter=None,
) -> FastAPI:
    app = FastAPI(title="bilive dashboard", version="0.1.0")
    store = DashboardFileStore(videos_root or default_videos_root())

    def _validated_slice_options(payload: Dict[str, Any] | None) -> dict[str, Any] | None:
        if not payload:
            return None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        opts = payload.get("slice_options")
        if opts is None:
            return None
        if not isinstance(opts, dict):
            raise HTTPException(status_code=400, detail="slice_options must be an object")
        allowed = {
            "burst_ratio",
            "burst_window",
            "burst_context",
            "burst_merge_gap",
            "burst_top_n",
        }
        unknown = sorted(set(opts) - allowed)
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown slice_options: {', '.join(unknown)}")

        def _float_option(name: str, minimum: float, maximum: float) -> float | None:
            if name not in opts:
                return None
            try:
                value = float(opts[name])
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{name} must be numeric") from exc
            if not minimum <= value <= maximum:
                raise HTTPException(status_code=400, detail=f"{name} must be {minimum}-{maximum}")
            return value

        def _int_option(name: str, minimum: int, maximum: int) -> int | None:
            if name not in opts:
                return None
            try:
                value = int(opts[name])
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc
            if not minimum <= value <= maximum:
                raise HTTPException(status_code=400, detail=f"{name} must be {minimum}-{maximum}")
            return value

        validated: dict[str, Any] = {}
        ratio = _float_option("burst_ratio", 1.5, 8.0)
        if ratio is not None:
            validated["burst_ratio"] = ratio

        for name, minimum, maximum in [
            ("burst_window", 5, 30),
            ("burst_merge_gap", 0, 30),
            ("burst_top_n", 1, 5),
        ]:
            value = _int_option(name, minimum, maximum)
            if value is not None:
                validated[name] = value

        if "burst_context" in opts:
            context = _int_option("burst_context", 30, 90)
            if context not in (30, 45, 60, 90):
                raise HTTPException(status_code=400, detail="burst_context must be 30/45/60/90")
            validated["burst_context"] = context
        return validated if validated else None

    def start_slicing(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if slice_starter is not None:
            if payload:
                return slice_starter(payload)
            return slice_starter()
        return start_slice_scan(
            store.videos_root,
            slice_options=_validated_slice_options(payload),
        )

    @app.get("/api/rooms")
    async def list_rooms() -> list[Dict[str, Any]]:
        return [room.to_dict() for room in store.list_rooms()]

    @app.get("/api/slices")
    async def list_slices(room_id: str | None = None) -> list[Dict[str, Any]]:
        try:
            return [item.to_dict() for item in store.list_slices(room_id)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks")
    async def list_tasks(room_id: str | None = None) -> list[Dict[str, Any]]:
        room_names = {room.room_id: room.name for room in store.list_rooms()}
        tasks = build_task_inventory(store.videos_root, room_id=room_id)
        for task in tasks:
            task["room_name"] = room_names.get(task["room_id"], task["room_id"])
        return tasks

    @app.post("/api/tasks/{task_id}/requeue")
    async def task_requeue(task_id: str) -> Dict[str, Any]:
        try:
            return requeue_task(store.videos_root, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/cancel-pending")
    async def task_cancel_pending(task_id: str) -> Dict[str, Any]:
        try:
            return cancel_pending_task(store.videos_root, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/mark-done")
    async def task_mark_done(task_id: str) -> Dict[str, Any]:
        try:
            return mark_done_task(store.videos_root, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/slice-progress")
    async def get_slice_progress() -> Dict[str, Any]:
        progress = load_progress_state()
        queue_state = load_pending_queue_state(store.videos_root)
        if queue_state["pending_tasks"] and (
            progress["status"] == "idle" or progress.get("stale")
        ):
            progress.update(
                status="queued",
                phase="queued",
                phase_label="已排队",
                message="等待本机 PC 切片 worker 处理",
                current_slice_percent=0.0,
                stale=False,
                **queue_state,
            )
        else:
            progress.update(queue_state)
        return progress

    @app.get("/api/slice-diagnostics")
    async def get_slice_diagnostics() -> Dict[str, Any]:
        progress = load_progress_state()
        queue_state = load_pending_queue_state(store.videos_root)
        return build_slice_diagnostics(progress, queue_state)

    @app.post("/api/slice/start")
    async def start_slice(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            return start_slicing(payload)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.patch("/api/slices/{slice_id}/feedback")
    async def update_feedback(
        slice_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            return store.write_feedback(slice_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/refine/preview")
    async def refine_preview() -> Dict[str, Any]:
        """Dry-run: count decisions and list what would be generated without writing files."""
        results = process_feedback_directory(store.videos_root, enqueue_upload=False, dry_run=True)
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

    @app.post("/api/refine/run")
    async def refine_run() -> Dict[str, Any]:
        """Execute refinement: generate clips for keep decisions, no upload queue by default."""
        results = process_feedback_directory(store.videos_root, enqueue_upload=False)
        keep_count = sum(1 for r in results if r.decision == "keep")
        refined = sum(1 for r in results if r.status == "refined")
        failed = sum(1 for r in results if r.status == "refine_failed")

        return {
            "keep_count": keep_count,
            "refined": refined,
            "failed": failed,
            "upload_queued": False,
        }

    @app.get("/api/media/{media_id}")
    async def get_media(media_id: str, request: Request) -> Response:
        try:
            path = store.resolve_media(media_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return media_response(path, request)

    @app.get("/api/preview/{media_id}")
    async def get_preview(media_id: str, request: Request) -> Response:
        try:
            path = store.resolve_preview_media(media_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return media_response(path, request, media_type="video/mp4")

    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            index_path = static_path / "index.html"

            if index_path.is_file():

                @app.get("/tasks", include_in_schema=False)
                async def tasks_page() -> FileResponse:
                    return FileResponse(index_path)

            app.mount("/", StaticFiles(directory=static_path, html=True), name="web")

    return app


def build_slice_diagnostics(
    progress: Dict[str, Any],
    queue_state: Dict[str, Any],
) -> Dict[str, Any]:
    pending_tasks = int(queue_state.get("pending_tasks") or 0)
    items = progress.get("diagnostics") if isinstance(progress.get("diagnostics"), list) else []
    if not items and pending_tasks:
        items = [
            {
                "id": "queue",
                "title": "任务队列",
                "status": "pending",
                "message": "等待本机 PC 切片 worker 处理",
                "details": [
                    {"label": "待处理", "value": str(pending_tasks)},
                    {
                        "label": "示例",
                        "value": ", ".join(queue_state.get("pending_sources") or []) or "-",
                    },
                ],
            }
        ]
    elif not items:
        items = [
            {
                "id": "idle",
                "title": "切片诊断",
                "status": "idle",
                "message": "暂无切片任务",
                "details": [],
            }
        ]

    status = "queued" if pending_tasks and progress.get("status") in {"idle", ""} else progress.get("status")
    return {
        "status": status or "idle",
        "phase": progress.get("phase") or "idle",
        "phase_label": progress.get("phase_label") or "",
        "source_name": progress.get("source_name") or "",
        "message": progress.get("message") or "",
        "updated_at": progress.get("updated_at") or 0.0,
        "pending_tasks": pending_tasks,
        "items": items,
    }


api = create_app(
    static_dir=os.environ.get(
        "BILIVE_DASHBOARD_STATIC",
        str(Path(__file__).resolve().parents[2] / "frontend"),
    )
)
