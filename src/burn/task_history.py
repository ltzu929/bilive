"""Per-source task history sidecars (`.mp4.task.json`).

Written alongside each source recording after processing to preserve outcome
data beyond the global `slice-progress.json` lifecycle.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def write_task_history(
    source_path: str | Path,
    *,
    status: str,
    videos_root: str | Path | None = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    worker_pid: Optional[int] = None,
    slice_count: int = 0,
    output_slices: Optional[List[str]] = None,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
    log_path: Optional[str] = None,
    error: Optional[str] = None,
) -> Path:
    """Write a `.mp4.task.json` sidecar for a processed source recording.

    Args:
        source_path: Path to the source .mp4 file.
        status: One of "done", "failed", "skipped", "cancelled".
        All other args: optional metadata.

    Returns:
        Path to the written .task.json file.
    """
    source = Path(source_path)
    history: Dict[str, Any] = {
        "source_rel_path": "",  # filled below if we can determine root
        "status": status,
        "started_at": started_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished_at": finished_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if worker_pid is not None:
        history["worker_pid"] = worker_pid

    if slice_count:
        history["slice_count"] = slice_count

    if output_slices:
        history["output_slices"] = output_slices

    if diagnostics:
        history["diagnostics"] = diagnostics

    if log_path:
        history["log_path"] = log_path

    if error:
        history["error"] = error

    # Determine source_rel_path from explicit root, VIDEOS_DIR env, or project root.
    videos_root = _videos_root(videos_root)
    try:
        history["source_rel_path"] = source.relative_to(videos_root).as_posix()
    except ValueError:
        history["source_rel_path"] = source.name

    task_path = source.with_suffix(".mp4.task.json")
    tmp_path = task_path.with_suffix(".task.json.tmp")
    tmp_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(task_path)
    return task_path


def read_task_history(source_path: str | Path) -> Optional[Dict[str, Any]]:
    """Read the .task.json sidecar if it exists."""
    task_path = Path(source_path).with_suffix(".mp4.task.json")
    if not task_path.is_file():
        return None
    try:
        return json.loads(task_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _videos_root(videos_root: str | Path | None = None) -> Path:
    if videos_root is not None:
        return Path(videos_root).expanduser().resolve()
    env = os.environ.get("BILIVE_VIDEOS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    project = os.environ.get(
        "BILIVE_RUNTIME_DIR",
        os.environ.get("BILIVE_DIR", str(Path(__file__).resolve().parents[2])),
    )
    return Path(project) / "Videos"
