# Copyright (c) 2024 bilive.
"""Pure helpers for the dashboard app.

Kept dependency-light (no FastAPI) so they can be unit-tested and re-exported
from :mod:`src.dashboard.app` without circular imports. Module level names here
are *not* part of any stable public API except the ones ``src.dashboard.app``
re-exports for back-compat (see that module's import block).
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterator

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from src.dashboard.file_store import DashboardFileStore


CHUNK_SIZE = 1024 * 1024

_RECORDING_NAME_RE = re.compile(
    r"^(?P<room>\d+)_(?P<date>\d{8})-(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})(?:_\(\d+\))?\.mp4$"
)


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
    return StreamingResponse(
        iter_file_range(path, start, end),
        status_code=206,
        media_type=response_media_type,
        headers=headers,
    )


def upload_path_parts(value: str) -> tuple[str, str]:
    text = str(value or "")
    path = PureWindowsPath(text) if "\\" in text else Path(text)
    return path.name or "-", path.parent.name or "-"


def read_upload_dashboard() -> Dict[str, Any]:
    from src.db import conn as upload_conn
    from src.server.upload_control import upload_worker_status

    db_path = Path(upload_conn.DATA_BASE_FILE)
    if not db_path.exists():
        return {
            "queue_counts": {
                "queued": 0,
                "uploading": 0,
                "uploaded": 0,
                "publishing": 0,
                "published": 0,
                "failed": 0,
                "total": 0,
            },
            "items": [],
            "database": f"unavailable: missing {db_path}",
            "worker": upload_worker_status(),
        }

    try:
        counts = upload_conn.get_upload_queue_counts()
        rows = upload_conn.list_upload_queue()
        database = "ready"
    except Exception as exc:
        counts = {"queued": 0, "uploading": 0, "uploaded": 0, "publishing": 0, "published": 0, "failed": 0, "total": 0}
        rows = []
        database = f"unavailable: {exc}"

    items = []
    for row in reversed(rows):
        name, room = upload_path_parts(str(row.get("video_path") or ""))
        items.append({
            "id": row.get("id"),
            "name": name,
            "room": room,
            "status": str(row.get("status") or "queued"),
            "attempts": int(row.get("attempts") or 0),
            "next_attempt_at": float(row.get("next_attempt_at") or 0),
            "last_error": str(row.get("last_error") or ""),
            "bvid": str(row.get("bvid") or ""),
            "updated_at": float(row.get("updated_at") or 0),
        })
    return {
        "queue_counts": counts,
        "items": items,
        "database": database,
        "worker": upload_worker_status(),
    }


def read_dashboard_settings() -> Dict[str, Any]:
    from src import config

    return {
        "slice": {
            "min_video_size_mb": config.MIN_VIDEO_SIZE,
            "burst_ratio": config.BURST_RATIO,
            "burst_window": config.BURST_WINDOW,
            "burst_context": config.BURST_CONTEXT,
            "burst_merge_gap": config.BURST_MERGE_GAP,
            "burst_top_n": config.BURST_TOP_N,
        },
        "mimo": {
            "model": config.MIMO_MODEL,
            "fps": config.MIMO_FPS,
            "media_resolution": config.MIMO_MEDIA_RESOLUTION,
            "timeout": config.MIMO_TIMEOUT,
            "parallelism": config.MIMO_PARALLELISM,
            "max_base64_bytes": config.MIMO_MAX_BASE64_BYTES,
            "configured": True if os.environ.get("MIMO_API_KEY") else None,
        },
        "whisper": {
            "model": config.MULTI_MODAL_WHISPER_MODEL,
            "engine": config.WHISPER_ENGINE,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
        },
        "upload": {
            "auto_start": config.UPLOAD_AUTO_START,
            "poll_interval_seconds": config.UPLOAD_POLL_INTERVAL_SECONDS,
            "max_attempts": config.UPLOAD_MAX_ATTEMPTS,
            "delete_after_success": config.UPLOAD_DELETE_AFTER_SUCCESS,
            "line": config.UPLOAD_LINE,
        },
    }


def process_feedback_directory(*args: Any, **kwargs: Any):
    from src.burn.feedback_refine import process_feedback_directory as process

    return process(*args, **kwargs)


# ── slice-progress enrichment (pure) ──────────────────────────────────────


def enrich_slice_progress(
    progress: Dict[str, Any],
    store: DashboardFileStore,
) -> Dict[str, Any]:
    enriched = dict(progress)
    source_name = Path(str(enriched.get("source_name") or enriched.get("source_path") or "")).name
    room_id = str(enriched.get("room_id") or "")
    match = _RECORDING_NAME_RE.match(source_name)
    if match and not room_id:
        room_id = match.group("room")

    room_name = room_id
    if room_id:
        room_names = {room.room_id: room.name for room in store.list_rooms()}
        room_name = room_names.get(room_id, room_id)

    source_rel_path = _progress_source_rel_path(
        enriched,
        room_id,
        source_name,
        store.videos_root,
    )
    recorded_at = _recording_time_label(source_name)
    display_parts = [part for part in [room_name or "", recorded_at] if part]
    enriched.update(
        {
            "room_id": room_id,
            "room_name": room_name,
            "recorded_at": recorded_at,
            "source_file": source_name,
            "source_rel_path": source_rel_path,
            "source_task_id": (
                _encode_source_task_id(source_rel_path) if source_rel_path else ""
            ),
            "display_title": " · ".join(display_parts) if display_parts else source_name,
        }
    )
    return enriched


def _progress_source_rel_path(
    progress: Dict[str, Any],
    room_id: str,
    source_name: str,
    videos_root: Path,
) -> str:
    source_path = str(progress.get("source_path") or "")
    if source_path:
        try:
            resolved = Path(source_path).expanduser().resolve()
            root = Path(videos_root).expanduser().resolve()
            return resolved.relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError):
            pass
    if room_id and source_name:
        return f"{room_id}/{source_name}"
    return ""


def _encode_source_task_id(source_rel_path: str) -> str:
    return (
        base64.urlsafe_b64encode(source_rel_path.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


def _recording_time_label(source_name: str) -> str:
    match = _RECORDING_NAME_RE.match(source_name or "")
    if not match:
        return ""
    date = match.group("date")
    return (
        f"{date[0:4]}-{date[4:6]}-{date[6:8]} "
        f"{match.group('hour')}:{match.group('minute')}:{match.group('second')}"
    )


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