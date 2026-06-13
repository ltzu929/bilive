# Copyright (c) 2024 bilive.

import mimetypes
import os
import ipaddress
from pathlib import Path
from typing import Any, Dict, Iterator
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.dashboard.file_store import DashboardFileStore
from src.dashboard.remote_worker import remote_worker_status, trigger_remote_worker
from src.dashboard.slice_control import load_pending_queue_state, start_slice_scan
from src.dashboard.task_state import (
    build_task_inventory,
    cancel_pending_task,
    mark_done_task,
    requeue_task,
)
from src.burn.slice_progress import load_progress_state
from src.server.action_jobs import enqueue_action_job, read_action_job


CHUNK_SIZE = 1024 * 1024


def _source_workbench_call(name: str, *args, **kwargs):
    from src.dashboard import source_workbench

    return getattr(source_workbench, name)(*args, **kwargs)


def build_source_recording_detail(*args, **kwargs):
    return _source_workbench_call(
        "build_source_recording_detail",
        *args,
        **kwargs,
    )


def build_source_recording_list(*args, **kwargs):
    return _source_workbench_call(
        "build_source_recording_list",
        *args,
        **kwargs,
    )


def drop_segment(*args, **kwargs):
    return _source_workbench_call("drop_segment", *args, **kwargs)


def manual_keep_segment(*args, **kwargs):
    return _source_workbench_call("manual_keep_segment", *args, **kwargs)


def render_segment(*args, **kwargs):
    return _source_workbench_call("render_segment", *args, **kwargs)


def retry_segment_judge(*args, **kwargs):
    return _source_workbench_call("retry_segment_judge", *args, **kwargs)


def update_segment_range(*args, **kwargs):
    return _source_workbench_call("update_segment_range", *args, **kwargs)


def process_feedback_directory(*args, **kwargs):
    from src.burn.feedback_refine import process_feedback_directory as process

    return process(*args, **kwargs)


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


def _segment_action(action) -> Dict[str, Any]:
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def create_app(
    videos_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    slice_starter=None,
    remote_worker_trigger=None,
    remote_worker_status_reader=None,
) -> FastAPI:
    app = FastAPI(title="bilive dashboard", version="0.1.0")
    store = DashboardFileStore(videos_root or default_videos_root())

    @app.middleware("http")
    async def validate_lan_request(request: Request, call_next):
        raw_host = request.headers.get("host", "").lower()
        try:
            host = (urlsplit(f"//{raw_host}").hostname or "").lower()
        except ValueError:
            host = ""
        configured = {
            value.strip().lower()
            for value in os.environ.get("BILIVE_DASHBOARD_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        }
        host_allowed = host in {"localhost", "test"} or host in configured
        if not host_allowed:
            try:
                host_allowed = ipaddress.ip_address(host).is_private
            except ValueError:
                host_allowed = False
        if not host_allowed:
            return JSONResponse({"detail": "Invalid dashboard host"}, status_code=400)

        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin_host = urlsplit(origin).netloc.lower()
            request_host = request.headers.get("host", "").lower()
            if origin_host != request_host:
                return JSONResponse(
                    {"detail": "Cross-origin dashboard write rejected"},
                    status_code=403,
                )
        return await call_next(request)

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

    def trigger_worker(pending_tasks: int) -> Dict[str, Any]:
        if remote_worker_trigger is not None:
            return remote_worker_trigger(pending_tasks)
        return trigger_remote_worker(pending_tasks=pending_tasks)

    def read_worker_trigger_status() -> Dict[str, Any]:
        if remote_worker_status_reader is not None:
            return remote_worker_status_reader()
        return remote_worker_status()

    def queue_segment_action(action: str, segment_id: str) -> Dict[str, Any]:
        result = enqueue_action_job(
            store.videos_root,
            action=action,
            segment_id=segment_id,
        )
        result["status_url"] = f"/api/jobs/{result['job']['job_id']}"
        result["worker_trigger"] = trigger_worker(1)
        return result

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

    @app.get("/api/source-recordings")
    async def list_source_recordings(room_id: str | None = None) -> list[Dict[str, Any]]:
        room_names = {room.room_id: room.name for room in store.list_rooms()}
        return build_source_recording_list(
            store.videos_root,
            room_names=room_names,
            room_id=room_id,
        )

    @app.get("/api/source-recordings/{task_id}")
    async def get_source_recording(task_id: str) -> Dict[str, Any]:
        room_names = {room.room_id: room.name for room in store.list_rooms()}
        try:
            return build_source_recording_detail(
                store.videos_root,
                task_id,
                room_names=room_names,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/segments/{segment_id}/manual-keep")
    async def segment_manual_keep(
        segment_id: str,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return _segment_action(
            lambda: manual_keep_segment(store.videos_root, segment_id, payload)
        )

    @app.post("/api/segments/{segment_id}/drop")
    async def segment_drop(
        segment_id: str,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return _segment_action(lambda: drop_segment(store.videos_root, segment_id, payload))

    @app.post("/api/segments/{segment_id}/range")
    async def segment_range(segment_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return _segment_action(lambda: update_segment_range(store.videos_root, segment_id, payload))

    @app.post("/api/segments/{segment_id}/retry-judge")
    async def segment_retry_judge(segment_id: str) -> Dict[str, Any]:
        return _segment_action(lambda: queue_segment_action("retry_judge", segment_id))

    @app.post("/api/segments/{segment_id}/render")
    async def segment_render(segment_id: str) -> Dict[str, Any]:
        return _segment_action(lambda: queue_segment_action("render_segment", segment_id))

    @app.get("/api/jobs/{job_id}")
    async def get_action_job(job_id: str) -> Dict[str, Any]:
        try:
            return read_action_job(store.videos_root, job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/requeue")
    async def task_requeue(task_id: str) -> Dict[str, Any]:
        try:
            result = requeue_task(store.videos_root, task_id)
            result["worker_trigger"] = trigger_worker(1)
            return result
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
            progress = build_queued_progress(queue_state)
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
            result = start_slicing(payload)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        pending_tasks = int(result.get("pending_tasks") or result.get("queued") or 0)
        if pending_tasks > 0:
            try:
                result["worker_trigger"] = trigger_worker(pending_tasks)
            except Exception as exc:  # pragma: no cover - defensive boundary
                result["worker_trigger"] = {
                    "status": "failed",
                    "message": str(exc),
                    "stdout": "",
                    "stderr": "",
                }
        return result

    @app.get("/api/worker-trigger/status")
    async def get_worker_trigger_status() -> Dict[str, Any]:
        return read_worker_trigger_status()

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
    show_queue = pending_tasks and (
        progress.get("status") in {"idle", ""} or progress.get("stale")
    )
    items = progress.get("diagnostics") if isinstance(progress.get("diagnostics"), list) else []
    if show_queue:
        items = build_queue_diagnostic_items(queue_state)
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

    status = "queued" if show_queue else progress.get("status")
    return {
        "status": status or "idle",
        "phase": "queued" if show_queue else progress.get("phase") or "idle",
        "phase_label": "已排队" if show_queue else progress.get("phase_label") or "",
        "source_name": "" if show_queue else progress.get("source_name") or "",
        "message": "等待本机 PC 切片 worker 处理" if show_queue else progress.get("message") or "",
        "updated_at": progress.get("updated_at") or 0.0,
        "pending_tasks": pending_tasks,
        "items": items,
    }


def build_queued_progress(queue_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "queued",
        "phase": "queued",
        "phase_label": "已排队",
        "room_id": "",
        "source_path": "",
        "source_name": "",
        "current_slice": 0,
        "total_slices": 0,
        "current_slice_path": "",
        "current_slice_percent": 0.0,
        "message": "等待本机 PC 切片 worker 处理",
        "error": "",
        "diagnostics": [],
        "updated_at": 0.0,
        "stale": False,
        **queue_state,
    }


def build_queue_diagnostic_items(queue_state: Dict[str, Any]) -> list[Dict[str, Any]]:
    pending_tasks = int(queue_state.get("pending_tasks") or 0)
    return [
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


api = create_app(
    static_dir=os.environ.get(
        "BILIVE_DASHBOARD_STATIC",
        str(Path(__file__).resolve().parents[2] / "frontend"),
    )
)
