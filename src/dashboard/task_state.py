"""Task inventory and status model for the bilive dashboard.

Provides a unified view of all source recordings and their processing state:
recording, ready, pending, running, done, failed, skipped, stale.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.burn.task_history import read_task_history, write_task_history
from src.config import MIN_VIDEO_SIZE


# Matches slice output names like "120s_22384516_20260527-12-55-32.mp4"
_SLICE_OUTPUT_RE = re.compile(r"^\d+(?:\.\d+)?s_.+\.mp4$")

# Source recording pattern: {room_id}_{YYYYMMDD-HH-MM-SS}.mp4
_SOURCE_RE = re.compile(r"^\d+_\d{8}-\d{2}-\d{2}-\d{2}(?:_\(\d+\))?\.mp4$")
MIN_SOURCE_RECORDING_SIZE_MB = MIN_VIDEO_SIZE

# Status descriptions in Chinese
_STATUS_MESSAGES: Dict[str, str] = {
    "recording": "录制中",
    "ready": "待处理",
    "pending": "已排队，等待 Windows 重任务节点",
    "processing": "Windows 重任务节点处理中",
    "running": "Windows 重任务节点处理中",
    "done": "已处理",
    "failed": "处理失败",
    "skipped": "已跳过（缺弹幕文件或过小）",
    "stale": "排队/运行超时",
}


def build_task_inventory(
    videos_root: str | Path,
    room_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a normalized task list for all source recordings.

    Args:
        videos_root: Path to the Videos directory.
        room_id: Optional filter to return tasks for a single room only.

    Returns:
        List of task dicts sorted by room_id and source_name.
    """
    root = Path(videos_root).expanduser().resolve()
    if not root.is_dir():
        return []

    tasks: List[Dict[str, Any]] = []

    room_dirs = sorted(
        [d for d in root.iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda d: d.name,
    )

    for room_dir in room_dirs:
        if room_id is not None and room_dir.name != room_id:
            continue

        sources = sorted(
            [
                f
                for f in room_dir.glob("*.mp4")
                if _SOURCE_RE.match(f.name) and _meets_min_source_size(f)
            ],
            key=lambda f: f.name,
        )

        for source in sources:
            task = _build_task(source, room_dir, root)
            tasks.append(task)

    return tasks


def _meets_min_source_size(source: Path) -> bool:
    minimum = float(MIN_SOURCE_RECORDING_SIZE_MB or 0)
    if minimum <= 0:
        return True
    try:
        return source.stat().st_size >= minimum * 1024 * 1024
    except OSError:
        return False


def _rel_path(p: Path, root: Path) -> str:
    """Return relative path with forward slashes for cross-platform consistency."""
    return p.relative_to(root).as_posix()


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _build_task(source: Path, room_dir: Path, root: Path) -> Dict[str, Any]:
    """Build a single task dict from a source .mp4 file."""
    source_name = source.name
    xml_path = source.with_suffix(".xml")
    pending_path = source.with_suffix(".mp4.pending")
    processing_path = source.with_suffix(".mp4.processing")
    failed_path = source.with_suffix(".mp4.failed")
    done_path = source.with_suffix(".mp4.done")

    has_xml = xml_path.is_file()
    has_pending = pending_path.is_file()
    has_processing = processing_path.is_file()
    has_failed = failed_path.is_file()
    has_done = done_path.is_file()

    source_rel = _rel_path(source, root)

    status = _determine_status(
        has_xml=has_xml,
        has_pending=has_pending,
        has_processing=has_processing,
        has_failed=has_failed,
        has_done=has_done,
        source=source,
    )

    message = _STATUS_MESSAGES.get(status, "")
    failure = None
    if has_failed and status == "failed":
        try:
            failure = json.loads(failed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failure = {
                "error": "Invalid failure marker",
                "error_type": "MarkerError",
            }
        message = str(failure.get("error") or message)

    # Enrich with task history if available. Active queue/done markers remain
    # authoritative so a stale failed sidecar does not hide a requeue/skip.
    history = read_task_history(source)
    if history:
        history_status = history.get("status")
        if (
            history_status == "failed"
            and not has_pending
            and not has_processing
            and not has_failed
            and not has_done
        ):
            status = "failed"
            message = history.get("error", "处理失败")
        elif history_status in {"done", "skipped"} and has_done:
            slice_count = history.get("slice_count")
            if slice_count:
                message = f"已处理，生成 {slice_count} 个切片"
            else:
                message = _history_result_message(history) or message

    task: Dict[str, Any] = {
        "task_id": _encode_task_id(source_rel),
        "room_id": room_dir.name,
        "room_name": room_dir.name,  # TODO: resolve UP name in future milestone
        "source_name": source_name,
        "source_rel_path": source_rel,
        "status": status,
        "pending_path": _rel_path(pending_path, root) if has_pending else None,
        "processing_path": (
            _rel_path(processing_path, root) if has_processing else None
        ),
        "failed_path": _rel_path(failed_path, root) if has_failed else None,
        "done_path": _rel_path(done_path, root) if has_done else None,
        "has_xml": has_xml,
        "source_size_mb": round(source.stat().st_size / (1024 * 1024), 1) if source.is_file() else 0.0,
        "updated_at": source.stat().st_mtime if source.is_file() else 0.0,
        "message": message,
        "failure": failure,
    }

    return task


def _history_result_message(history: Dict[str, Any]) -> Optional[str]:
    diagnostics = history.get("diagnostics")
    if not isinstance(diagnostics, list):
        return None

    for item in diagnostics:
        if not isinstance(item, dict) or item.get("id") != "result":
            continue
        message = item.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def _encode_task_id(source_rel_path: str) -> str:
    """Encode a relative source path for use in URL path segments."""
    return base64.urlsafe_b64encode(source_rel_path.encode("utf-8")).decode("ascii").rstrip("=")


def _determine_status(
    *,
    has_xml: bool,
    has_pending: bool,
    has_processing: bool,
    has_failed: bool,
    has_done: bool,
    source: Path,
) -> str:
    """Determine the task status from sidecar files and source state."""
    # Done takes highest priority
    if has_done:
        return "done"

    if has_processing:
        return "processing"

    if has_pending:
        return "pending"

    if has_failed:
        return "failed"

    # Without XML, the source is not sliceable
    if not has_xml:
        return "skipped"

    # Ready: has XML, no pending, no done
    return "ready"


# ── Recovery action helpers ──


def resolve_task_id(videos_root: str | Path, task_id: str) -> Path:
    """Decode a base64 task_id into a resolved source .mp4 path under videos_root.

    Raises ValueError for invalid IDs or paths outside videos_root.
    Raises FileNotFoundError if the resolved file doesn't exist.
    """
    root = Path(videos_root).expanduser().resolve()
    try:
        padded = task_id + "=" * ((4 - len(task_id) % 4) % 4)
        relative = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Invalid task id") from exc

    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("Path outside videos root") from None

    if not resolved.is_file():
        raise FileNotFoundError(f"Source not found: {relative}")

    return resolved


def requeue_task(videos_root: str | Path, task_id: str) -> Dict[str, Any]:
    """Remove .done, write a fresh .pending marker."""
    source = resolve_task_id(videos_root, task_id)
    root = Path(videos_root).expanduser().resolve()
    done = source.with_suffix(".mp4.done")
    pending = source.with_suffix(".mp4.pending")
    processing = source.with_suffix(".mp4.processing")
    failed = source.with_suffix(".mp4.failed")

    if processing.exists():
        raise ValueError("Task is currently processing")

    rel = source.relative_to(root).as_posix()
    marker = {
        "video_rel_path": rel,
        "room_id": source.parent.name,
        "action": "slice",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_by": "dashboard-requeue",
    }
    _write_json_atomic(pending, marker)
    try:
        write_task_history(
            source,
            status="pending",
            videos_root=root,
            started_at=marker["created_at"],
        )
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    done.unlink(missing_ok=True)
    failed.unlink(missing_ok=True)

    return {"status": "requeued", "task_id": task_id, "source_rel_path": rel}


def cancel_pending_task(videos_root: str | Path, task_id: str) -> Dict[str, Any]:
    """Remove .pending marker only. Source .mp4 and .xml are preserved."""
    source = resolve_task_id(videos_root, task_id)
    pending = source.with_suffix(".mp4.pending")
    processing = source.with_suffix(".mp4.processing")

    if processing.exists():
        raise ValueError("Task is currently processing")

    if not pending.exists():
        return {"status": "no_pending", "task_id": task_id}

    pending.unlink()
    return {"status": "cancelled", "task_id": task_id}


def mark_done_task(videos_root: str | Path, task_id: str) -> Dict[str, Any]:
    """Write .done marker without slicing (manual skip)."""
    source = resolve_task_id(videos_root, task_id)
    root = Path(videos_root).expanduser().resolve()
    done = source.with_suffix(".mp4.done")
    pending = source.with_suffix(".mp4.pending")
    processing = source.with_suffix(".mp4.processing")
    failed = source.with_suffix(".mp4.failed")

    if processing.exists():
        raise ValueError("Task is currently processing")

    rel = source.relative_to(root).as_posix()
    marker = {
        "video_rel_path": rel,
        "room_id": source.parent.name,
        "action": "skip",
        "created_by": "dashboard-mark-done",
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write_json_atomic(done, marker)
    if pending.exists():
        pending.unlink()
    if failed.exists():
        failed.unlink()
    write_task_history(
        source,
        status="done",
        videos_root=root,
        started_at=marker["processed_at"],
        finished_at=marker["processed_at"],
    )

    return {"status": "marked_done", "task_id": task_id, "source_rel_path": rel}
