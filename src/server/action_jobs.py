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


SUPPORTED_ACTIONS = {
    "retry_judge",
    "render_segment",
    "reburn_subtitles",
    "finalize_segment",
    "create_missed_segment",
    "trash_recording",
}
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
JOB_STATES = ("pending", "processing", "done", "failed")
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_HELD_LOCKS = threading.local()


@contextmanager
def action_submission_lock(videos_root: str | Path):
    """Serialize review edits, enqueue and publication before waking workers."""
    root = jobs_dir(videos_root)
    root.mkdir(parents=True, exist_ok=True)
    with _queue_lock(root / ".enqueue.lock"):
        yield


class ActionJobExecutionError(RuntimeError):
    """Action failure with a dashboard-safe structured description."""

    def __init__(self, failure: dict[str, str]) -> None:
        self.failure = failure
        super().__init__(failure["summary"])


class SegmentActionConflict(RuntimeError):
    """A segment already has a pending or processing action."""


def jobs_dir(videos_root: str | Path) -> Path:
    return Path(videos_root).expanduser().resolve() / ".bilive-jobs"


def enqueue_action_job(
    videos_root: str | Path,
    *,
    action: str,
    segment_id: str = "",
    recording_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported action job: {action}")
    segment = str(segment_id).strip()
    recording = str(recording_id).strip()
    if not segment and not recording:
        raise ValueError("segment_id or recording_id is required")
    if segment and recording:
        raise ValueError("segment_id and recording_id are mutually exclusive")

    root = jobs_dir(videos_root)
    root.mkdir(parents=True, exist_ok=True)
    normalized_payload = dict(payload or {})
    with _queue_lock(root / ".enqueue.lock"):
        existing = find_active_segment_job(videos_root, segment)
        if recording:
            existing = find_active_recording_job(videos_root, recording)
        if existing is not None:
            if (
                existing.get("action") == action
                and dict(existing.get("payload") or {}) == normalized_payload
            ):
                return {"status": "already_pending", "job": existing}
            raise SegmentActionConflict(
                f"segment already has active action: {existing.get('action')}"
            )

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        job = {
            "job_id": uuid.uuid4().hex,
            "action": action,
            "segment_id": segment,
            "execution_target": "windows",
            "status": "pending",
            "created_at": now,
            "created_ns": time.time_ns(),
            "updated_at": now,
        }
        if segment:
            job["segment_id"] = segment
        if recording:
            job["recording_id"] = recording
        if normalized_payload:
            job["payload"] = normalized_payload
        _write_json_atomic(_state_path(root, job["job_id"], "pending"), job)
    return {"status": "accepted", "job": job}


def read_action_job(videos_root: str | Path, job_id: str) -> dict[str, Any]:
    identifier = _validate_job_id(job_id)
    root = jobs_dir(videos_root)
    for state in JOB_STATES:
        path = _state_path(root, identifier, state)
        if path.is_file():
            return _read_json(path)
    invalid = root / f"{identifier}.invalid.json"
    if invalid.is_file():
        return {"job_id": identifier, "status": "blocked", "failure": {
            "code": "corrupt_action", "summary": "任务文件损坏，需要人工核对",
            "recovery_action": "检查保留的 invalid 文件和关联片段，未自动重试"}}
    raise FileNotFoundError(f"Action job not found: {identifier}")


def count_pending_action_jobs(videos_root: str | Path) -> int:
    root = jobs_dir(videos_root)
    if not root.is_dir():
        return 0
    count = 0
    for path in root.glob("*.pending.json"):
        try:
            _read_pending_job(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        count += 1
    return count


def claim_next_action_job(videos_root: str | Path) -> tuple[Path, dict[str, Any]] | None:
    root = jobs_dir(videos_root)
    if not root.is_dir():
        return None
    with action_submission_lock(videos_root), _queue_lock(root / ".claim.lock"):
        candidates = []
        for path in root.glob("*.pending.json"):
            try:
                job = _read_pending_job(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _quarantine_invalid_pending(path, exc)
                continue
            candidates.append(
                (
                    int(job.get("created_ns") or 0),
                    str(job.get("created_at") or ""),
                    str(job.get("job_id") or ""),
                    path,
                    job,
                )
            )
        selected = min(candidates, default=None)
        pending = selected[3] if selected is not None else None
        if pending is None:
            return None
        job = selected[4]
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
    with action_submission_lock(videos_root), _queue_lock(root / ".claim.lock"):
        for processing in sorted(root.glob("*.processing.json")):
            try:
                job = _read_pending_job(processing)
            except (OSError, ValueError) as exc:
                _quarantine_invalid_pending(processing, exc)
                continue
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
            _record_segment_job_state(root, job, "processing")
            result = execute(job)
            _record_segment_job_state(root, job, "done")
            _finish_job(processing, job, status="done", result=result)
            completed += 1
        except Exception as exc:
            failure = _structured_failure_from_exception(job, exc)
            _record_segment_job_state(root, job, "failed", failure=failure)
            _finish_job(
                processing,
                job,
                status="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                failure=failure,
            )
    return completed


def _execute_action_job(videos_root: Path, job: dict[str, Any]) -> dict[str, Any]:
    if os.name != "nt":
        raise ActionJobExecutionError(
            {
                "stage": "dispatch",
                "code": "windows_worker_required",
                "summary": "片段重任务必须由 Windows worker 执行",
                "technical_details": f"worker platform: os.name={os.name}",
                "recovery_action": "启动 Windows worker 后重试该任务",
            }
        )

    from src.dashboard.source_workbench import (
        create_missed_segment,
        finalize_segment,
        reburn_segment_subtitles,
        render_segment,
        retry_segment_judge,
    )
    from src.dashboard.recording_trash import trash_recording

    if job["action"] == "retry_judge":
        return retry_segment_judge(videos_root, job["segment_id"])
    if job["action"] == "render_segment":
        return render_segment(videos_root, job["segment_id"])
    if job["action"] == "reburn_subtitles":
        return reburn_segment_subtitles(videos_root, job["segment_id"])
    if job["action"] == "finalize_segment":
        payload = dict(job.get("payload") or {})
        payload.pop("_review_request", None)
        payload["_job_id"] = str(job.get("job_id") or "")
        return finalize_segment(
            videos_root,
            job["segment_id"],
            payload=payload,
        )
    if job["action"] == "create_missed_segment":
        return create_missed_segment(
            videos_root,
            job["segment_id"],
            payload=dict(job.get("payload") or {}),
        )
    if job["action"] == "trash_recording":
        payload = dict(job.get("payload") or {})
        payload.pop("_review_request", None)
        payload["_job_id"] = str(job.get("job_id") or "")
        return trash_recording(
            videos_root,
            str(job.get("recording_id") or ""),
            payload=payload,
        )
    raise ValueError(f"Unsupported action job: {job['action']}")


def _quarantine_invalid_pending(path: Path, exc: Exception) -> None:
    """Move an unreadable pending file out of the claimable queue."""
    invalid = path.with_name(path.name.replace(".pending.json", ".invalid.json").replace(".processing.json", ".invalid.json"))
    try:
        os.replace(path, invalid)
    except OSError:
        return
    try:
        invalid.with_suffix(f"{invalid.suffix}.error").write_text(
            f"{type(exc).__name__}: {exc}",
            encoding="utf-8",
        )
    except OSError:
        pass


def _read_pending_job(path: Path) -> dict[str, Any]:
    job = _read_json(path)
    expected_job_id = path.name.split(".", 1)[0]
    if (
        str(job.get("job_id") or "") != expected_job_id
        or not JOB_ID_RE.fullmatch(expected_job_id)
        or str(job.get("action") or "") not in SUPPORTED_ACTIONS
        or not bool(
            str(job.get("segment_id") or "").strip()
            or str(job.get("recording_id") or "").strip()
        )
        or bool(
            str(job.get("segment_id") or "").strip()
            and str(job.get("recording_id") or "").strip()
        )
    ):
        raise ValueError("pending action job has invalid or inconsistent fields")
    return job


def _finish_job(
    processing: Path,
    job: dict[str, Any],
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
    error_type: str = "",
    failure: dict[str, str] | None = None,
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
    if failure is not None:
        payload["failure"] = failure
    destination = _state_path(processing.parent, payload["job_id"], status)
    _write_json_atomic(destination, payload)
    processing.unlink(missing_ok=True)


def _structured_failure_from_exception(
    job: dict[str, Any],
    exc: Exception,
) -> dict[str, str]:
    failure = getattr(exc, "failure", None)
    if isinstance(failure, dict):
        required = {
            "stage",
            "code",
            "summary",
            "technical_details",
            "recovery_action",
        }
        if required.issubset(failure):
            return {key: str(failure.get(key) or "") for key in required}
    action = str(job.get("action") or "action")
    return {
        "stage": action,
        "code": f"{action}_failed",
        "summary": str(exc) or type(exc).__name__,
        "technical_details": f"{type(exc).__name__}: {exc}",
        "recovery_action": "检查技术详情后重试该任务",
    }


def _corrupt_job_target(videos_root: str | Path, path: Path) -> dict[str, str]:
    identifier = path.name.split(".", 1)[0]
    try:
        data = _read_json(path)
        if data.get("segment_id") or data.get("recording_id"):
            return {key: str(data.get(key) or "") for key in ("segment_id", "recording_id")}
    except (OSError, ValueError):
        pass
    for history_path in Path(videos_root).glob("*/*.mp4.task.json"):
        try:
            history = _read_json(history_path)
        except (OSError, ValueError):
            continue
        for segment in history.get("segments") or []:
            if isinstance(segment, dict) and (segment.get("action_state") or {}).get("job_id") == identifier:
                return {"segment_id": str(segment.get("segment_id") or "")}
    return {}


def find_active_segment_job(
    videos_root: str | Path,
    segment_id: str,
) -> dict[str, Any] | None:
    root = jobs_dir(videos_root)
    for state in ("pending", "processing", "invalid"):
        for path in sorted(root.glob(f"*.{state}.json")):
            try:
                job = _read_pending_job(path)
            except (OSError, ValueError) as exc:
                target = _corrupt_job_target(videos_root, path)
                if target and target.get("segment_id") != segment_id:
                    continue
                raise SegmentActionConflict(f"任务文件损坏，需要人工核对: {path.name}") from exc
            if job.get("segment_id") == segment_id:
                return job
    return None


def find_active_recording_job(
    videos_root: str | Path,
    recording_id: str,
) -> dict[str, Any] | None:
    root = jobs_dir(videos_root)
    for state in ("pending", "processing", "invalid"):
        for path in sorted(root.glob(f"*.{state}.json")):
            try:
                job = _read_pending_job(path)
            except (OSError, ValueError) as exc:
                target = _corrupt_job_target(videos_root, path)
                if target and target.get("recording_id") != recording_id:
                    continue
                raise SegmentActionConflict(f"任务文件损坏，需要人工核对: {path.name}") from exc
            if job.get("recording_id") == recording_id:
                return job
    return None


def _record_segment_job_state(
    videos_root: Path,
    job: dict[str, Any],
    status: str,
    *,
    failure: dict[str, str] | None = None,
) -> None:
    if os.name != "nt":
        return
    if not str(job.get("segment_id") or "").strip():
        _record_recording_job_state(videos_root, job, status, failure=failure)
        return
    try:
        from src.dashboard.source_workbench import record_segment_action_state

        record_segment_action_state(
            videos_root,
            str(job.get("segment_id") or ""),
            status=status,
            job_id=str(job.get("job_id") or ""),
            action=str(job.get("action") or ""),
            failure=failure,
        )
    except Exception:
        # The job file remains authoritative even if a damaged/missing history
        # cannot be synchronized. Do not mask the original action outcome.
        return


def _record_recording_job_state(
    videos_root: Path,
    job: dict[str, Any],
    status: str,
    *,
    failure: dict[str, str] | None = None,
) -> None:
    recording_id = str(job.get("recording_id") or "").strip()
    if not recording_id:
        return
    try:
        from src.dashboard.source_lifecycle import set_trash_job_state

        reason = ""
        if failure:
            reason = str(failure.get("summary") or failure.get("technical_details") or "")
        set_trash_job_state(
            videos_root,
            recording_id,
            status=status,
            job_id=str(job.get("job_id") or ""),
            reason=reason,
        )
    except Exception:
        # Keep the action-job file authoritative if the independent recording
        # state is missing or damaged.
        return


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
    held = getattr(_HELD_LOCKS, "paths", set())
    if key in held:
        yield
        return
    with _THREAD_LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        for attempt in range(attempts):
            lock = WorkerProcessLock(path)
            try:
                lock.__enter__()
            except WorkerAlreadyRunning:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(delay)
                continue
            _HELD_LOCKS.paths = held | {key}
            try:
                yield
            finally:
                _HELD_LOCKS.paths = held
                lock.__exit__(None, None, None)
            return
