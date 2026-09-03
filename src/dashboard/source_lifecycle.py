"""Independent source-recording lifecycle, profile, and experience state.

The files in ``Videos/.bilive-state`` deliberately live outside the source
recording package.  A source recording may be moved to the Windows Recycle
Bin, while its review decision, experience records, and streamer profile must
remain available to the dashboard.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Any, Callable

from src.server.worker_lock import WorkerProcessLock


REVIEW_STATES = (
    "unprocessed",
    "processing",
    "candidate_review",
    "source_review",
    "review_complete",
    "trash_pending",
)
REVIEWABLE_STATUSES = {"keep", "manual_keep", "drop"}
UNRESOLVED_STATUSES = {"review", "judge_failed"}
RETENTION_WARNING_DAYS = 11
RETENTION_DAYS = 14
MISSED_SEGMENT_REASONS = {
    "mimo_missed": "MiMo 漏切",
    "boundary_incomplete": "边界不完整",
    "low_danmaku_signal": "弹幕信号弱",
    "other": "其他",
}
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ROOM_ID_RE = re.compile(r"^\d+$")
_SOURCE_RE = re.compile(
    r"^(?P<room>\d+)_(?P<date>\d{8})-(?P<hour>\d{2})-"
    r"(?P<minute>\d{2})-(?P<second>\d{2})(?:_\(\d+\))?\.mp4$"
)
_STATE_LOCKS: dict[str, threading.Lock] = {}
_STATE_LOCKS_GUARD = threading.Lock()


class RecordingStateConflict(RuntimeError):
    """The requested lifecycle transition is not safe to perform."""


class RecordingTrashBlocked(RecordingStateConflict):
    """Source cleanup was refused and includes a dashboard-safe reason."""

    def __init__(self, reason: str, *, blockers: list[str] | None = None) -> None:
        self.reason = str(reason)
        self.blockers = [str(item) for item in (blockers or []) if str(item)]
        self.failure = {
            "stage": "trash",
            "code": "trash_blocked",
            "summary": self.reason,
            "technical_details": ", ".join(self.blockers),
            "recovery_action": "完成整场复核并等待活跃任务结束后重试回收",
        }
        super().__init__(self.reason)


def state_root(videos_root: str | Path) -> Path:
    return Path(videos_root).expanduser().resolve() / ".bilive-state"


def recordings_state_dir(videos_root: str | Path) -> Path:
    return state_root(videos_root) / "recordings"


def streamer_state_dir(videos_root: str | Path) -> Path:
    return state_root(videos_root) / "streamers"


def recording_state_path(videos_root: str | Path, task_id: str) -> Path:
    identifier = _validate_task_id(task_id)
    return recordings_state_dir(videos_root) / f"{identifier}.json"


def streamer_state_path(videos_root: str | Path, room_id: str) -> Path:
    return streamer_state_dir(videos_root) / f"{_validate_room_id(room_id)}.json"


def _validate_task_id(task_id: str) -> str:
    identifier = str(task_id or "").strip()
    if not identifier or not _TASK_ID_RE.fullmatch(identifier):
        raise ValueError("Invalid task id")
    return identifier


def _validate_room_id(room_id: str) -> str:
    identifier = str(room_id or "").strip()
    if not _ROOM_ID_RE.fullmatch(identifier):
        raise ValueError("Invalid room id")
    return identifier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@contextmanager
def _state_lock(path: Path):
    key = str(path.resolve())
    with _STATE_LOCKS_GUARD:
        thread_lock = _STATE_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        with WorkerProcessLock(path.with_suffix(path.suffix + ".lock")):
            yield


def default_recording_state(
    task_id: str,
    source_rel_path: str,
    room_id: str,
    *,
    recorded_at: str = "",
) -> dict[str, Any]:
    start = _recording_epoch(source_rel_path)
    if start is None:
        start = time.time()
    started_at = datetime.fromtimestamp(start, timezone.utc).isoformat(
        timespec="seconds"
    )
    deadline = datetime.fromtimestamp(
        start + RETENTION_DAYS * 86400,
        timezone.utc,
    ).isoformat(timespec="seconds")
    return {
        "task_id": _validate_task_id(task_id),
        "source_rel_path": str(source_rel_path),
        "room_id": _validate_room_id(room_id),
        "recorded_at": str(recorded_at or ""),
        "review_state": "unprocessed",
        "review_state_updated_at": _now(),
        "review_started_at": "",
        "review_completed_at": "",
        "review_completion": {},
        "retention_started_at": started_at,
        "retention_deadline": deadline,
        "trash_status": "",
        "trash_job_id": "",
        "trash_block_reason": "",
        "trash_files": [],
        "trash_completed_at": "",
        "experience_ids": [],
        "updated_at": _now(),
    }


def read_recording_state(
    videos_root: str | Path,
    task_id: str,
) -> dict[str, Any] | None:
    return _read_json(recording_state_path(videos_root, task_id))


def get_recording_state(
    videos_root: str | Path,
    task_id: str,
    *,
    source_rel_path: str = "",
    room_id: str = "",
    recorded_at: str = "",
) -> dict[str, Any]:
    current = read_recording_state(videos_root, task_id)
    if current is not None:
        return current
    return default_recording_state(
        task_id,
        source_rel_path,
        room_id,
        recorded_at=recorded_at,
    )


def mutate_recording_state(
    videos_root: str | Path,
    task_id: str,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    source_rel_path: str = "",
    room_id: str = "",
    recorded_at: str = "",
) -> dict[str, Any]:
    path = recording_state_path(videos_root, task_id)
    with _state_lock(path):
        current = _read_json(path)
        if current is None:
            current = default_recording_state(
                task_id,
                source_rel_path,
                room_id,
                recorded_at=recorded_at,
            )
        updated = mutator(dict(current))
        if not isinstance(updated, dict):
            raise TypeError("recording state mutator must return an object")
        updated["task_id"] = _validate_task_id(task_id)
        if source_rel_path:
            updated.setdefault("source_rel_path", str(source_rel_path))
        if room_id:
            updated.setdefault("room_id", _validate_room_id(room_id))
        updated["updated_at"] = _now()
        _atomic_write(path, updated)
        return updated


def derive_review_state(
    task_status: str,
    history_status: str,
    segments: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
) -> str:
    explicit = str((state or {}).get("review_state") or "")
    if explicit == "trash_pending":
        return explicit
    if task_status in {"pending", "processing", "running"} or history_status == "processing":
        return "processing"
    if explicit == "processing":
        return explicit
    if explicit == "review_complete":
        return explicit
    if explicit == "source_review" and segments:
        return "candidate_review"
    if not history_status and task_status in {"ready", "skipped"}:
        return "unprocessed"
    if not segments:
        return "source_review" if history_status in {"done", "skipped"} else "unprocessed"
    if any(
        str(segment.get("judge_status") or "review") in UNRESOLVED_STATUSES
        for segment in segments
    ):
        return "candidate_review"
    return "candidate_review"


def retention_fields(
    state: dict[str, Any],
    *,
    now: float | None = None,
    trash_block_reason: str = "",
    source_exists: bool = True,
    review_ready: bool | None = None,
) -> dict[str, Any]:
    current_time = time.time() if now is None else float(now)
    started = _parse_iso_epoch(state.get("retention_started_at"))
    deadline = _parse_iso_epoch(state.get("retention_deadline"))
    if started is None:
        started = current_time
    if deadline is None:
        deadline = started + RETENTION_DAYS * 86400
    completed = str(state.get("trash_status") or "") == "done"
    if review_ready is None:
        review_ready = str(state.get("review_state") or "") in {
            "review_complete",
            "trash_pending",
        }
    warning = current_time >= started + RETENTION_WARNING_DAYS * 86400
    expired = current_time >= deadline
    return {
        "retention_deadline": datetime.fromtimestamp(
            deadline, timezone.utc
        ).isoformat(timespec="seconds"),
        "retention_warning": bool(warning and not completed and not review_ready),
        "retention_expired": bool(expired and not completed),
        "trash_eligible": bool(
            source_exists
            and not completed
            and not trash_block_reason
            and (bool(review_ready) or expired)
        ),
        "trash_block_reason": str(trash_block_reason or ""),
    }


def build_lifecycle_view(
    videos_root: str | Path,
    task: dict[str, Any],
    history: dict[str, Any] | None,
    segments: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    task_id = str(task.get("task_id") or "")
    source_rel_path = str(task.get("source_rel_path") or "")
    room_id = str(task.get("room_id") or "")
    source = (root / source_rel_path).resolve()
    state = get_recording_state(
        root,
        task_id,
        source_rel_path=source_rel_path,
        room_id=room_id,
        recorded_at=str(task.get("recorded_at") or ""),
    )
    review_state = derive_review_state(
        str(task.get("status") or ""),
        str((history or {}).get("status") or ""),
        segments,
        state,
    )
    blocker = ""
    if not source.is_file():
        blocker = "源录播文件不存在"
    elif task.get("status") in {"pending", "processing", "running"}:
        blocker = "录播切片任务正在运行"
    elif not source.with_suffix(".mp4.done").is_file():
        blocker = "录播任务状态不明，缺少完成标记"
    elif review_state == "processing":
        blocker = "录播任务仍处于处理中"
    elif any(
        str(segment.get("judge_status") or "review") in UNRESOLVED_STATUSES
        for segment in segments
    ):
        blocker = "仍有候选片段未完成复核"
    elif str(state.get("trash_status") or "") in {"failed", "blocked"}:
        blocker = str(state.get("trash_block_reason") or "上次回收失败")
    else:
        from src.server.action_jobs import (
            find_active_recording_job,
            find_active_segment_job,
        )

        if find_active_recording_job(root, task_id) is not None:
            blocker = "录播仍有回收任务正在运行"
        for segment in segments:
            if blocker:
                break
            segment_id = str(segment.get("segment_id") or "")
            if segment_id and find_active_segment_job(root, segment_id) is not None:
                blocker = "仍有片段任务正在运行"
                break
            paths: list[Path] = []
            artifacts = segment.get("artifacts")
            if isinstance(artifacts, dict):
                paths.extend(
                    root / str(item.get("rel_path"))
                    for item in artifacts.values()
                    if isinstance(item, dict) and item.get("rel_path")
                )
            candidate_rel = str(segment.get("candidate_rel_path") or "")
            if candidate_rel:
                paths.append(root / candidate_rel)
            if paths:
                from src.db import conn as upload_conn
                from src.db.conn import get_upload_item

                if not Path(upload_conn.DATA_BASE_FILE).is_file():
                    blocker = "无法确认片段上传状态"
                    continue
                for path in paths:
                    try:
                        upload_item = get_upload_item(str(path))
                    except Exception:
                        blocker = "无法确认片段上传状态"
                        break
                    if upload_item and str(upload_item.get("status") or "") in {
                        "uploading",
                        "publishing",
                    }:
                        blocker = "仍有片段正在上传或发布"
                        break
    retention = retention_fields(state, now=now, source_exists=source.is_file())
    if (
        not blocker
        and review_state not in {"review_complete", "trash_pending"}
        and not retention["retention_expired"]
    ):
        blocker = "尚未完成整场复核"
    fields = retention_fields(
        state,
        now=now,
        trash_block_reason=blocker,
        source_exists=source.is_file(),
        review_ready=review_state in {"review_complete", "trash_pending"},
    )
    return {
        "review_state": review_state,
        **fields,
        "trash_status": str(state.get("trash_status") or ""),
        "trash_job_id": str(state.get("trash_job_id") or ""),
        "review_completed_at": str(state.get("review_completed_at") or ""),
    }


def set_review_state(
    videos_root: str | Path,
    task_id: str,
    review_state: str,
    *,
    source_rel_path: str,
    room_id: str,
    recorded_at: str = "",
    completion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if review_state not in REVIEW_STATES:
        raise ValueError(f"Invalid review state: {review_state}")

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        previous = str(state.get("review_state") or "")
        state["review_state"] = review_state
        state["review_state_updated_at"] = _now()
        if review_state == "processing" and not state.get("review_started_at"):
            state["review_started_at"] = _now()
        if review_state == "review_complete":
            state["review_completed_at"] = _now()
            state["review_completion"] = dict(completion or {})
        if previous == "review_complete" and review_state == "trash_pending":
            state["trash_block_reason"] = ""
        return state

    return mutate_recording_state(
        videos_root,
        task_id,
        mutate,
        source_rel_path=source_rel_path,
        room_id=room_id,
        recorded_at=recorded_at,
    )


def set_trash_job_state(
    videos_root: str | Path,
    task_id: str,
    *,
    status: str,
    job_id: str = "",
    reason: str = "",
    files: list[str] | None = None,
) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        state["trash_status"] = str(status)
        if job_id:
            state["trash_job_id"] = str(job_id)
        state["trash_block_reason"] = str(reason or "")
        if files is not None:
            state["trash_files"] = [str(path) for path in files]
        if status == "done":
            state["trash_completed_at"] = _now()
        return state

    return mutate_recording_state(videos_root, task_id, mutate)


def append_trash_log(
    videos_root: str | Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Append one source-recycle result to the independent lifecycle log."""
    path = state_root(videos_root) / "trash-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("created_at", _now())
    with _state_lock(path):
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def _parse_iso_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _recording_epoch(source_rel_path: str) -> float | None:
    match = _SOURCE_RE.match(Path(str(source_rel_path)).name)
    if not match:
        return None
    try:
        value = datetime.strptime(
            "".join(
                match.group(key)
                for key in ("date", "hour", "minute", "second")
            ),
            "%Y%m%d%H%M%S",
        )
    except ValueError:
        return None
    return value.replace(tzinfo=timezone.utc).timestamp()


def _experience_path(videos_root: str | Path) -> Path:
    return state_root(videos_root) / "experiences.jsonl"


def read_experiences(
    videos_root: str | Path,
    *,
    room_id: str | None = None,
) -> list[dict[str, Any]]:
    path = _experience_path(videos_root)
    if not path.is_file():
        return []
    requested_room = str(room_id) if room_id is not None else None
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if requested_room is not None and str(record.get("room_id") or "") != requested_room:
            continue
        records.append(record)
    return records


def append_experience(
    videos_root: str | Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    path = _experience_path(videos_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    dedupe_key = str(record.get("dedupe_key") or "")
    with _state_lock(path):
        existing = read_experiences(videos_root)
        if dedupe_key:
            for item in existing:
                if str(item.get("dedupe_key") or "") == dedupe_key:
                    return item
        payload = dict(record)
        payload.setdefault("experience_id", uuid.uuid4().hex)
        payload.setdefault("created_at", _now())
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return payload


def record_review_experiences(
    videos_root: str | Path,
    *,
    room_id: str,
    task_id: str,
    source_rel_path: str,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not segments:
        records.append(
            append_experience(
                videos_root,
                {
                    "room_id": room_id,
                    "task_id": task_id,
                    "source_rel_path": source_rel_path,
                    "experience_type": "recording_no_content",
                    "conclusion": "no_content",
                    "reason_type": "recording_empty",
                    "note": "整场复核确认没有精彩片段",
                    "dedupe_key": f"{task_id}:recording_no_content",
                },
            )
        )
    for segment in segments:
        status = str(segment.get("judge_status") or "review")
        failure = segment.get("failure")
        technical_after_manual_drop = (
            status == "drop"
            and (
                bool(segment.get("_technical_failure"))
                or (isinstance(failure, dict) and bool(failure))
            )
        )
        if status == "judge_failed" or technical_after_manual_drop:
            experience_type = "technical_failure"
            conclusion = "technical_failure"
        elif status in UNRESOLVED_STATUSES:
            experience_type = "unresolved"
            conclusion = "unresolved"
        elif str(segment.get("manual_origin") or "") == "missed_segment":
            experience_type = "missed_segment_positive"
            conclusion = "positive"
        elif status in {"keep", "manual_keep"}:
            experience_type = "positive"
            conclusion = "positive"
        elif status == "drop":
            experience_type = "negative"
            conclusion = "negative"
        else:
            continue
        segment_id = str(segment.get("segment_id") or "")
        reason = str(
            segment.get("missed_reason")
            or segment.get("quality_reason")
            or segment.get("judge_error")
            or ""
        ).strip()
        if experience_type == "technical_failure" and isinstance(failure, dict):
            reason = str(
                failure.get("technical_details")
                or failure.get("summary")
                or reason
            ).strip()
        reason_type = str(segment.get("missed_reason") or "content_review")
        note = str(
            segment.get("review_note")
            or segment.get("quality_reason")
            or ""
        ).strip()
        if experience_type == "technical_failure" and isinstance(failure, dict):
            reason_type = ":".join(
                item
                for item in (
                    str(failure.get("stage") or "technical"),
                    str(failure.get("code") or "technical_failure"),
                )
                if item
            )
            note = str(
                failure.get("summary")
                or failure.get("technical_details")
                or note
            ).strip()
        records.append(
            append_experience(
                videos_root,
                {
                    "room_id": room_id,
                    "task_id": task_id,
                    "source_rel_path": source_rel_path,
                    "segment_id": segment_id,
                    "start_seconds": _number(segment.get("start_seconds")),
                    "end_seconds": _number(segment.get("end_seconds")),
                    "experience_type": experience_type,
                    "conclusion": conclusion,
                    "reason_type": reason_type,
                    "note": note,
                    "reason": reason,
                    "model_judgment": status,
                    "model_scores": {
                        key: segment.get(key)
                        for key in ("quality_score", "completeness_score", "confidence")
                        if segment.get(key) is not None
                    },
                    "transcript_summary": _text_summary(
                        segment.get("transcript") or segment.get("transcript_summary")
                    ),
                    "danmaku_summary": {
                        "count": int(_number(segment.get("danmaku_count")) or 0),
                        "text": _text_summary(
                            segment.get("danmaku_text") or segment.get("danmaku_summary")
                        ),
                    },
                    "dedupe_key": f"{task_id}:{segment_id}:{experience_type}:{segment.get('revision', 0)}",
                },
            )
        )
    if records:
        experience_ids = [
            str(item.get("experience_id") or "")
            for item in records
            if str(item.get("experience_id") or "")
        ]

        def remember(state: dict[str, Any]) -> dict[str, Any]:
            known = [
                str(item)
                for item in state.get("experience_ids", [])
                if str(item)
            ]
            state["experience_ids"] = list(dict.fromkeys(known + experience_ids))
            return state

        mutate_recording_state(
            videos_root,
            task_id,
            remember,
            source_rel_path=source_rel_path,
            room_id=room_id,
        )
    generate_streamer_recommendation(videos_root, room_id)
    return records


def record_technical_experience(
    videos_root: str | Path,
    *,
    room_id: str,
    task_id: str,
    source_rel_path: str,
    segment: dict[str, Any],
    failure: dict[str, Any],
    job_id: str = "",
) -> dict[str, Any]:
    """Persist a technical failure without treating it as content feedback."""
    stage = str(failure.get("stage") or "technical")
    code = str(failure.get("code") or "technical_failure")
    segment_id = str(segment.get("segment_id") or "")
    dedupe = job_id or str(segment.get("revision") or "0")
    record = append_experience(
        videos_root,
        {
            "room_id": room_id,
            "task_id": task_id,
            "source_rel_path": source_rel_path,
            "segment_id": segment_id,
            "start_seconds": _number(segment.get("start_seconds")),
            "end_seconds": _number(segment.get("end_seconds")),
            "experience_type": "technical_failure",
            "conclusion": "technical_failure",
            "reason_type": f"{stage}:{code}",
            "note": str(
                failure.get("summary")
                or failure.get("technical_details")
                or "技术任务失败"
            ).strip(),
            "reason": str(failure.get("technical_details") or "").strip(),
            "model_judgment": str(segment.get("judge_status") or ""),
            "model_scores": {
                key: segment.get(key)
                for key in ("quality_score", "completeness_score", "confidence")
                if segment.get(key) is not None
            },
            "transcript_summary": _text_summary(
                segment.get("transcript") or segment.get("transcript_summary")
            ),
            "danmaku_summary": {
                "count": int(_number(segment.get("danmaku_count")) or 0),
                "text": _text_summary(
                    segment.get("danmaku_text") or segment.get("danmaku_summary")
                ),
            },
            "dedupe_key": f"{task_id}:{segment_id}:technical_failure:{dedupe}",
        },
    )
    experience_id = str(record.get("experience_id") or "")
    if experience_id:
        def remember(state: dict[str, Any]) -> dict[str, Any]:
            known = [
                str(item)
                for item in state.get("experience_ids", [])
                if str(item)
            ]
            state["experience_ids"] = list(dict.fromkeys(known + [experience_id]))
            return state

        mutate_recording_state(
            videos_root,
            task_id,
            remember,
            source_rel_path=source_rel_path,
            room_id=room_id,
        )
    return record


def generate_streamer_recommendation(
    videos_root: str | Path,
    room_id: str,
    *,
    min_samples: int = 5,
) -> dict[str, Any]:
    room = _validate_room_id(room_id)
    experiences = read_experiences(videos_root, room_id=room)
    valid = [
        item
        for item in experiences
        if item.get("experience_type") in {
            "positive",
            "negative",
            "missed_segment_positive",
        }
    ]
    positive = [
        item
        for item in valid
        if item.get("conclusion") == "positive"
    ]
    negative = [
        item
        for item in valid
        if item.get("conclusion") == "negative"
    ]
    base = {
        "evidence_status": "insufficient_evidence",
        "sample_size": len(valid),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "message": "证据不足：至少需要 5 条有效人工样本，且同时包含正、负样本",
    }
    if len(valid) < max(1, int(min_samples)) or not positive or not negative:
        return base

    reason_counts = Counter(
        str(item.get("reason_type") or "content_review")
        for item in negative + [
            item for item in valid if item.get("experience_type") == "missed_segment_positive"
        ]
    )
    reasons = [item for item, _count in reason_counts.most_common(3)]
    guidance = "；".join(reasons) if reasons else "保留完整主题、发展和落点"
    guidance = f"人工样本提示：重点检查 {guidance}。"
    evidence_ids = [str(item.get("experience_id") or "") for item in valid]

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        recommendations = data.get("recommendations")
        if not isinstance(recommendations, list):
            recommendations = []
        for item in recommendations:
            if isinstance(item, dict) and item.get("evidence_ids") == evidence_ids:
                return data
        recommendations.append(
            {
                "recommendation_id": uuid.uuid4().hex,
                "room_id": room,
                "created_at": _now(),
                "status": "pending",
                "evidence_status": "ready",
                "sample_size": len(valid),
                "positive_count": len(positive),
                "negative_count": len(negative),
                "evidence_ids": evidence_ids,
                "basis": [
                    {
                        "experience_id": item.get("experience_id"),
                        "experience_type": item.get("experience_type"),
                        "conclusion": item.get("conclusion"),
                        "reason_type": item.get("reason_type"),
                    }
                    for item in valid
                ],
                "changes": {"approved_guidance": guidance},
                "message": "建议只影响该主播，需人工点击应用",
            }
        )
        data["recommendations"] = recommendations
        return data

    current = read_streamer_state(videos_root, room) or {
        "room_id": room,
        "profile": default_streamer_profile(room),
        "recommendations": [],
    }
    return mutate_streamer_state(videos_root, room, mutate)


def default_streamer_profile(room_id: str) -> dict[str, Any]:
    return {
        "room_id": _validate_room_id(room_id),
        "display_name": "",
        "aliases": [],
        "default_tags": [],
        "default_description": "",
        "default_slice_options": {},
        "default_subtitle_style": {},
        "approved_guidance": "",
        "updated_at": "",
    }


def read_streamer_state(
    videos_root: str | Path,
    room_id: str,
) -> dict[str, Any] | None:
    return _read_json(streamer_state_path(videos_root, room_id))


def read_streamer_profile(
    videos_root: str | Path,
    room_id: str,
) -> dict[str, Any]:
    room = _validate_room_id(room_id)
    state = read_streamer_state(videos_root, room)
    profile = state.get("profile") if isinstance(state, dict) else None
    if not isinstance(profile, dict):
        return default_streamer_profile(room)
    return {**default_streamer_profile(room), **profile}


def read_streamer_recommendations(
    videos_root: str | Path,
    room_id: str,
) -> list[dict[str, Any]]:
    state = read_streamer_state(videos_root, room_id) or {}
    recommendations = state.get("recommendations")
    return [dict(item) for item in recommendations if isinstance(item, dict)] if isinstance(recommendations, list) else []


def mutate_streamer_state(
    videos_root: str | Path,
    room_id: str,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    room = _validate_room_id(room_id)
    path = streamer_state_path(videos_root, room)
    with _state_lock(path):
        current = _read_json(path) or {
            "room_id": room,
            "profile": default_streamer_profile(room),
            "recommendations": [],
            "updated_at": _now(),
        }
        updated = mutator(dict(current))
        updated["room_id"] = room
        updated["updated_at"] = _now()
        _atomic_write(path, updated)
        return updated


def patch_streamer_profile(
    videos_root: str | Path,
    room_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    room = _validate_room_id(room_id)
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    allowed = {
        "display_name",
        "aliases",
        "default_tags",
        "default_description",
        "default_slice_options",
        "default_subtitle_style",
        "approved_guidance",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown profile fields: {', '.join(unknown)}")

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        profile = {**default_streamer_profile(room), **(state.get("profile") or {})}
        if "display_name" in payload:
            profile["display_name"] = str(payload.get("display_name") or "").strip()
        for key in ("aliases", "default_tags"):
            if key not in payload:
                continue
            value = payload.get(key)
            if not isinstance(value, list):
                raise ValueError(f"{key} must be an array")
            profile[key] = [str(item).strip() for item in value if str(item).strip()]
        for key in ("default_description", "approved_guidance"):
            if key in payload:
                profile[key] = str(payload.get(key) or "")
        if "default_slice_options" in payload:
            profile["default_slice_options"] = _normalize_slice_options(
                payload.get("default_slice_options")
            )
        if "default_subtitle_style" in payload:
            profile["default_subtitle_style"] = _normalize_subtitle_style(
                payload.get("default_subtitle_style")
            )
        profile["updated_at"] = _now()
        state["profile"] = profile
        return state

    return mutate_streamer_state(videos_root, room, mutate).get("profile", {})


def apply_streamer_recommendation(
    videos_root: str | Path,
    room_id: str,
    recommendation_id: str,
) -> dict[str, Any]:
    room = _validate_room_id(room_id)
    identifier = str(recommendation_id or "").strip()
    if not _TASK_ID_RE.fullmatch(identifier):
        raise ValueError("Invalid recommendation id")

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        recommendations = state.get("recommendations")
        if not isinstance(recommendations, list):
            raise FileNotFoundError("Recommendation not found")
        recommendation = next(
            (
                item
                for item in recommendations
                if isinstance(item, dict)
                and str(item.get("recommendation_id") or "") == identifier
            ),
            None,
        )
        if recommendation is None:
            raise FileNotFoundError("Recommendation not found")
        profile = {**default_streamer_profile(room), **(state.get("profile") or {})}
        if str(recommendation.get("status") or "") != "applied":
            changes = recommendation.get("changes") or {}
            if "approved_guidance" in changes:
                profile["approved_guidance"] = str(
                    changes.get("approved_guidance") or ""
                )
            if isinstance(changes.get("default_slice_options"), dict):
                profile["default_slice_options"] = _normalize_slice_options(
                    changes["default_slice_options"]
                )
            profile["updated_at"] = _now()
            recommendation["status"] = "applied"
            recommendation["applied_at"] = _now()
            state["profile"] = profile
        return state

    state = mutate_streamer_state(videos_root, room, mutate)
    profile = {**default_streamer_profile(room), **(state.get("profile") or {})}
    recommendation = next(
        item
        for item in state.get("recommendations", [])
        if isinstance(item, dict)
        and str(item.get("recommendation_id") or "") == identifier
    )
    return {"profile": profile, "recommendation": recommendation}


def profile_slice_options(
    videos_root: str | Path,
    room_id: str,
) -> dict[str, Any]:
    profile = read_streamer_profile(videos_root, room_id)
    value = profile.get("default_slice_options")
    return dict(value) if isinstance(value, dict) else {}


def profile_subtitle_style(
    videos_root: str | Path,
    room_id: str,
) -> dict[str, Any]:
    profile = read_streamer_profile(videos_root, room_id)
    value = profile.get("default_subtitle_style")
    return dict(value) if isinstance(value, dict) else {}


def profile_context_for_mimo(
    videos_root: str | Path,
    room_id: str,
) -> str:
    profile = read_streamer_profile(videos_root, room_id)
    guidance = str(profile.get("approved_guidance") or "").strip()
    if not guidance:
        return ""
    return guidance[:2000]


def _normalize_slice_options(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("default_slice_options must be an object")
    allowed = {
        "burst_ratio",
        "burst_window",
        "burst_context",
        "burst_merge_gap",
        "burst_top_n",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown default_slice_options: {', '.join(unknown)}")
    result: dict[str, Any] = {}
    for key, raw in value.items():
        if key == "burst_ratio":
            number = _number(raw)
            if number is None or not 1.5 <= number <= 8:
                raise ValueError("default burst_ratio must be 1.5-8")
            result[key] = number
        else:
            try:
                number = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"default {key} must be an integer") from exc
            limits = {
                "burst_window": (5, 30),
                "burst_context": (30, 120),
                "burst_merge_gap": (0, 30),
                "burst_top_n": (1, 5),
            }
            minimum, maximum = limits[key]
            if not minimum <= number <= maximum:
                raise ValueError(f"default {key} must be {minimum}-{maximum}")
            result[key] = number
    return result


def _normalize_subtitle_style(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("default_subtitle_style must be an object")
    from src.burn.subtitle_burn import SubtitleStyle

    return SubtitleStyle.from_mapping(value).to_mapping()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _text_summary(value: Any, limit: int = 1000) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]
