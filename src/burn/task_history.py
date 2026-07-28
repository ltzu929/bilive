"""Per-source task history sidecars (`.mp4.task.json`).

Written alongside each source recording after processing to preserve outcome
data beyond the global `slice-progress.json` lifecycle.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.server.worker_lock import WorkerAlreadyRunning, WorkerProcessLock


ACTIVE_STATUSES = {"pending", "processing"}


def task_history_path(source_path: str | Path) -> Path:
    return Path(source_path).with_suffix(".mp4.task.json")


def task_history_lock_path(source_path: str | Path) -> Path:
    task_path = task_history_path(source_path)
    return task_path.with_name(f"{task_path.name}.lock")


@contextmanager
def lock_task_history(
    source_path: str | Path,
    *,
    attempts: int = 400,
    delay: float = 0.01,
):
    """Serialize task-history read/modify/write across dashboard and worker."""
    lock_path = task_history_lock_path(source_path)
    for attempt in range(max(1, int(attempts))):
        lock = WorkerProcessLock(lock_path)
        try:
            lock.__enter__()
        except WorkerAlreadyRunning:
            if attempt + 1 >= attempts:
                raise
            time.sleep(delay)
            continue
        try:
            yield
        finally:
            lock.__exit__(None, None, None)
        return


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
    segments: Optional[List[Dict[str, Any]]] = None,
    diagnostics: Optional[List[Dict[str, Any]]] = None,
    log_path: Optional[str] = None,
    error: Optional[str] = None,
    failure: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a `.mp4.task.json` sidecar for a processed source recording.

    Args:
        source_path: Path to the source .mp4 file.
        status: One of "pending", "processing", "done", "failed",
            "skipped", or "cancelled".
        All other args: optional metadata.

    Returns:
        Path to the written .task.json file.
    """
    source = Path(source_path)
    task_path = task_history_path(source)
    with lock_task_history(source):
        previous = read_task_history(source) or {}
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        history: Dict[str, Any] = {
            "source_rel_path": "",  # filled below if we can determine root
            "status": status,
            "updated_at": now,
        }
        queued_at = previous.get("queued_at")
        if status == "pending":
            history["queued_at"] = queued_at or started_at or now
        elif status == "processing":
            if queued_at:
                history["queued_at"] = queued_at
            history["started_at"] = started_at or now
        else:
            if queued_at:
                history["queued_at"] = queued_at
            history["started_at"] = started_at or previous.get("started_at") or now
            history["finished_at"] = finished_at or now

        if worker_pid is not None:
            history["worker_pid"] = worker_pid

        if slice_count:
            history["slice_count"] = slice_count

        if output_slices:
            history["output_slices"] = output_slices

        if segments is not None:
            history["segments"] = segments

        if diagnostics:
            history["diagnostics"] = diagnostics

        if log_path:
            history["log_path"] = log_path

        if error:
            history["error"] = error

        if failure:
            history["failure"] = dict(failure)

        # Determine source_rel_path from explicit root, VIDEOS_DIR env, or project root.
        resolved_videos_root = _videos_root(videos_root)
        try:
            history["source_rel_path"] = source.relative_to(
                resolved_videos_root
            ).as_posix()
        except ValueError:
            history["source_rel_path"] = source.name

        tmp_path = task_path.with_name(
            f"{task_path.name}.{os.getpid()}.{threading.get_ident()}."
            f"{uuid.uuid4().hex}.tmp"
        )
        tmp_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, task_path)
        return task_path


def read_task_history(source_path: str | Path) -> Optional[Dict[str, Any]]:
    """Read the .task.json sidecar if it exists."""
    task_path = task_history_path(source_path)
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
