from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from src.burn.task_history import write_task_history


SLICE_OUTPUT_RE = re.compile(r"^\d+(?:\.\d+)?s_.+\.mp4$")


def start_slice_scan(
    videos_root: str | Path | None = None,
    slice_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue completed recordings for the PC-side slice worker.

    The dashboard may run on the Pi, so this function must stay lightweight:
    it writes .pending marker files only and never starts the slicer locally.

    Optional slice_options (burst_ratio, burst_context, burst_top_n) are written
    into each pending marker for the PC worker to read.
    """
    root = Path(videos_root) if videos_root is not None else _default_videos_root()
    root = root.expanduser().resolve()
    queued_paths: list[str] = []
    skipped = 0

    if not root.is_dir():
        return {
            "status": "missing_videos_root",
            "queued": 0,
            "skipped": 0,
            "videos_root": str(root),
        }

    existing_pending = load_pending_queue_state(root)["pending_tasks"]
    for room_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if not room_dir.is_dir() or not room_dir.name.isdigit():
            continue
        for video_path in sorted(room_dir.glob("*.mp4"), key=lambda item: item.name):
            if not _is_queue_candidate(video_path):
                skipped += 1
                continue
            pending_path = _write_pending_marker(video_path, root, slice_options=slice_options)
            queued_paths.append(str(pending_path))

    return {
        "status": "queued" if queued_paths or existing_pending else "empty",
        "queued": len(queued_paths),
        "pending_tasks": existing_pending + len(queued_paths),
        "skipped": skipped,
        "videos_root": str(root),
        "pending_paths": queued_paths,
    }


def load_pending_queue_state(videos_root: str | Path) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    if not root.is_dir():
        return {"pending_tasks": 0, "pending_sources": []}

    pending_files = sorted(root.rglob("*.mp4.pending"), key=lambda item: str(item))
    return {
        "pending_tasks": len(pending_files),
        "pending_sources": [
            path.with_suffix("").name
            for path in pending_files[:5]
        ],
    }


def _default_videos_root() -> Path:
    env_path = os.environ.get("BILIVE_VIDEOS_DIR")
    if env_path:
        return Path(env_path)
    runtime_root = Path(
        os.environ.get(
            "BILIVE_RUNTIME_DIR",
            os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2]),
        )
    )
    return runtime_root / "Videos"


def _is_queue_candidate(video_path: Path) -> bool:
    if video_path.name.endswith("-.mp4"):
        return False
    if "_slice" in video_path.name or SLICE_OUTPUT_RE.match(video_path.name):
        return False
    if not video_path.with_suffix(".xml").is_file():
        return False
    if video_path.with_suffix(".mp4.pending").exists():
        return False
    if video_path.with_suffix(".mp4.done").exists():
        return False
    return True


def _write_pending_marker(
    video_path: Path,
    videos_root: Path,
    slice_options: dict[str, Any] | None = None,
) -> Path:
    pending_path = video_path.with_suffix(".mp4.pending")
    rel_path = video_path.relative_to(videos_root).as_posix()
    marker_data: dict[str, Any] = {
        "video_rel_path": rel_path,
        "room_id": video_path.parent.name,
        "action": "slice",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_by": "dashboard",
    }
    if slice_options:
        marker_data["slice_options"] = slice_options
    tmp_path = pending_path.with_suffix(pending_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(marker_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(pending_path)
    try:
        write_task_history(
            video_path,
            status="pending",
            videos_root=videos_root,
            started_at=marker_data["created_at"],
        )
    except Exception:
        pending_path.unlink(missing_ok=True)
        raise
    return pending_path
