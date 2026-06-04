"""Task inventory and status model for the bilive dashboard.

Provides a unified view of all source recordings and their processing state:
recording, ready, pending, running, done, failed, skipped, stale.
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.burn.task_history import read_task_history


# Matches slice output names like "120s_22384516_20260527-12-55-32.mp4"
_SLICE_OUTPUT_RE = re.compile(r"^\d+(?:\.\d+)?s_.+\.mp4$")

# Source recording pattern: {room_id}_{YYYYMMDD-HH-MM-SS}.mp4
_SOURCE_RE = re.compile(r"^\d+_\d{8}-\d{2}-\d{2}-\d{2}\.mp4$")

# Status descriptions in Chinese
_STATUS_MESSAGES: Dict[str, str] = {
    "recording": "录制中",
    "ready": "待处理",
    "pending": "已排队，等待 PC worker",
    "running": "PC worker 处理中",
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
            [f for f in room_dir.glob("*.mp4") if _SOURCE_RE.match(f.name)],
            key=lambda f: f.name,
        )

        for source in sources:
            task = _build_task(source, room_dir, root)
            tasks.append(task)

    return tasks


def _rel_path(p: Path, root: Path) -> str:
    """Return relative path with forward slashes for cross-platform consistency."""
    return p.relative_to(root).as_posix()


def _build_task(source: Path, room_dir: Path, root: Path) -> Dict[str, Any]:
    """Build a single task dict from a source .mp4 file."""
    source_name = source.name
    xml_path = source.with_suffix(".xml")
    pending_path = source.with_suffix(".mp4.pending")
    done_path = source.with_suffix(".mp4.done")

    has_xml = xml_path.is_file()
    has_pending = pending_path.is_file()
    has_done = done_path.is_file()

    source_rel = _rel_path(source, root)

    status = _determine_status(
        has_xml=has_xml,
        has_pending=has_pending,
        has_done=has_done,
        source=source,
    )

    message = _STATUS_MESSAGES.get(status, "")

    # Enrich with task history if available. Active queue/done markers remain
    # authoritative so a stale failed sidecar does not hide a requeue/skip.
    history = read_task_history(source)
    if history:
        history_status = history.get("status")
        if history_status == "failed" and not has_pending and not has_done:
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
        "done_path": _rel_path(done_path, root) if has_done else None,
        "has_xml": has_xml,
        "source_size_mb": round(source.stat().st_size / (1024 * 1024), 1) if source.is_file() else 0.0,
        "updated_at": source.stat().st_mtime if source.is_file() else 0.0,
        "message": message,
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
    has_done: bool,
    source: Path,
) -> str:
    """Determine the task status from sidecar files and source state."""
    # Done takes highest priority
    if has_done:
        return "done"

    # Without XML, the source is not sliceable
    if not has_xml:
        return "skipped"

    # Pending means it's queued for the worker
    if has_pending:
        return "pending"

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

    if done.exists():
        done.unlink()

    rel = source.relative_to(root).as_posix()
    marker = {
        "video_rel_path": rel,
        "room_id": source.parent.name,
        "action": "slice",
        "created_by": "dashboard-requeue",
    }
    pending.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "requeued", "task_id": task_id, "source_rel_path": rel}


def cancel_pending_task(videos_root: str | Path, task_id: str) -> Dict[str, Any]:
    """Remove .pending marker only. Source .mp4 and .xml are preserved."""
    source = resolve_task_id(videos_root, task_id)
    pending = source.with_suffix(".mp4.pending")

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

    rel = source.relative_to(root).as_posix()
    marker = {
        "video_rel_path": rel,
        "room_id": source.parent.name,
        "action": "skip",
        "created_by": "dashboard-mark-done",
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    done.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    if pending.exists():
        pending.unlink()

    return {"status": "marked_done", "task_id": task_id, "source_rel_path": rel}
