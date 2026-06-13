"""Persistent Windows-only action jobs created by the Pi dashboard."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from src.server.worker_lock import (
    WorkerAlreadyRunning,
    WorkerProcessLock,
    pid_is_running,
)


SUPPORTED_ACTIONS = {"retry_judge", "render_segment"}
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
JOB_STATES = ("pending", "processing", "done", "failed")
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def jobs_dir(videos_root: str | Path) -> Path:
    return Path(videos_root).expanduser().resolve() / ".bilive-jobs"


def enqueue_action_job(
    videos_root: str | Path,
    *,
    action: str,
    segment_id: str,
) -> dict[str, Any]:
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported action job: {action}")
    segment = str(segment_id).strip()
    if not segment:
        raise ValueError("segment_id is required")

    root = jobs_dir(videos_root)
    root.mkdir(parents=True, exist_ok=True)
    with _queue_lock(root / ".enqueue.lock"):
        existing = _find_active_job(root, action=action, segment_id=segment)
        if existing is not None:
            return {"status": "already_pending", "job": existing}

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job = {
            "job_id": uuid.uuid4().hex,
            "action": action,
            "segment_id": segment,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        _write_json_atomic(_state_path(root, job["job_id"], "pending"), job)
    return {"status": "accepted", "job": job}


def read_action_job(videos_root: str | Path, job_id: str) -> dict[str, Any]:
    identifier = _validate_job_id(job_id)
    root = jobs_dir(videos_root)
    for state in JOB_STATES:
        path = _state_path(root, identifier, state)
        if path.is_file():
            return _read_json(path)
    raise FileNotFoundError(f"Action job not found: {identifier}")


def count_pending_action_jobs(videos_root: str | Path) -> int:
    root = jobs_dir(videos_root)
    return len(list(root.glob("*.pending.json"))) if root.is_dir() else 0


def claim_next_action_job(videos_root: str | Path) -> tuple[Path, dict[str, Any]] | None:
    root = jobs_dir(videos_root)
    if not root.is_dir():
        return None
    with _queue_lock(root / ".claim.lock"):
        pending = next(iter(sorted(root.glob("*.pending.json"))), None)
        if pending is None:
            return None
        job = _read_json(pending)
        processing = _state_path(root, job["job_id"], "processing")
        os.replace(pending, processing)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job.update(
            {
                "status": "processing",
                "worker_pid": os.getpid(),
                "started_at": now,
                "updated_at": now,
            }
        )
        _write_json_atomic(processing, job)
        return processing, job


def recover_action_jobs(
    videos_root: str | Path,
    *,
    pid_checker: Callable[[int], bool] = pid_is_running,
) -> int:
    root = jobs_dir(videos_root)
    if not root.is_dir():
        return 0
    recovered = 0
    with _queue_lock(root / ".claim.lock"):
        for processing in sorted(root.glob("*.processing.json")):
            job = _read_json(processing)
            try:
                owner = int(job.get("worker_pid") or 0)
            except (TypeError, ValueError):
                owner = 0
            if owner > 0 and pid_checker(owner):
                continue
            job.pop("worker_pid", None)
            job.update(
                {
                    "status": "pending",
                    "recovered_from": "processing",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            pending = _state_path(root, job["job_id"], "pending")
            _write_json_atomic(pending, job)
            processing.unlink(missing_ok=True)
            recovered += 1
    return recovered


def process_action_jobs(
    videos_root: str | Path,
    *,
    executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> int:
    root = Path(videos_root).expanduser().resolve()
    recover_action_jobs(root)
    execute = executor or (lambda job: _execute_action_job(root, job))
    completed = 0
    while True:
        claimed = claim_next_action_job(root)
        if claimed is None:
            break
        processing, job = claimed
        try:
            result = execute(job)
            _finish_job(processing, job, status="done", result=result)
            completed += 1
        except Exception as exc:
            _finish_job(
                processing,
                job,
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
    return completed


def _execute_action_job(videos_root: Path, job: dict[str, Any]) -> dict[str, Any]:
    from src.dashboard.source_workbench import render_segment, retry_segment_judge

    if job["action"] == "retry_judge":
        return retry_segment_judge(videos_root, job["segment_id"])
    if job["action"] == "render_segment":
        return render_segment(videos_root, job["segment_id"])
    raise ValueError(f"Unsupported action job: {job['action']}")


def _finish_job(
    processing: Path,
    job: dict[str, Any],
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
    error_type: str = "",
) -> None:
    payload = dict(job)
    payload.pop("worker_pid", None)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    payload.update({"status": status, "updated_at": now, "finished_at": now})
    if result is not None:
        payload["result"] = result
    if error:
        payload["error"] = error
        payload["error_type"] = error_type
    destination = _state_path(processing.parent, payload["job_id"], status)
    _write_json_atomic(destination, payload)
    processing.unlink(missing_ok=True)


def _find_active_job(
    root: Path,
    *,
    action: str,
    segment_id: str,
) -> dict[str, Any] | None:
    for state in ("pending", "processing"):
        for path in sorted(root.glob(f"*.{state}.json")):
            job = _read_json(path)
            if job.get("action") == action and job.get("segment_id") == segment_id:
                return job
    return None


def _state_path(root: Path, job_id: str, state: str) -> Path:
    return root / f"{_validate_job_id(job_id)}.{state}.json"


def _validate_job_id(job_id: str) -> str:
    identifier = str(job_id)
    if not JOB_ID_RE.fullmatch(identifier):
        raise ValueError("Invalid action job id")
    return identifier


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Action job is not an object: {path}")
    return data


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def _queue_lock(path: Path, attempts: int = 200, delay: float = 0.01):
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        for attempt in range(attempts):
            lock = WorkerProcessLock(path)
            try:
                with lock:
                    yield
                return
            except WorkerAlreadyRunning:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(delay)
