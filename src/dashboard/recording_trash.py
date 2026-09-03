"""Windows-only source-recording recycle-bin actions.

The dashboard only creates an action job.  This module is called by the
Windows worker, resolves the exact source package from task history, and uses
the Windows shell's undoable delete operation so files enter the Recycle Bin.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any, Callable

from src.burn.task_history import read_task_history
from src.dashboard.source_lifecycle import (
    RecordingTrashBlocked,
    append_trash_log,
    mutate_recording_state,
    read_recording_state,
    set_trash_job_state,
)
from src.dashboard.task_state import resolve_task_id
from src.db import conn as upload_conn
from src.db.conn import get_upload_item
from src.server.action_jobs import find_active_segment_job, find_active_recording_job


_ACTIVE_UPLOAD_STATUSES = {"uploading", "publishing"}
_MARKER_SUFFIXES = (".mp4.pending", ".mp4.processing", ".mp4.failed", ".mp4.done")
_SOURCE_SIDECAR_SUFFIXES = (".xml", ".json", ".ass")
_CANDIDATE_SIDECAR_SUFFIXES = ("_analysis.json", "_asr.srt", ".features.json")


def build_trash_plan(
    videos_root: str | Path,
    task_id: str,
    *,
    payload: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    options = dict(payload or {})
    state = read_recording_state(root, task_id) or {}
    if str(state.get("trash_status") or "") == "done":
        return {
            "status": "already_trashed",
            "task_id": task_id,
            "files": list(state.get("trash_files") or []),
            "blockers": [],
        }

    try:
        source = resolve_task_id(root, task_id)
    except FileNotFoundError:
        raise RecordingTrashBlocked("源录播文件不存在", blockers=["source_missing"])
    except ValueError as exc:
        raise RecordingTrashBlocked("录播任务标识无效", blockers=[str(exc)]) from exc

    history = read_task_history(source) or {}
    segments = history.get("segments")
    if not isinstance(segments, list):
        segments = []
    blockers: list[str] = []
    marker_paths = [source.with_suffix(suffix) for suffix in _MARKER_SUFFIXES]
    if marker_paths[0].is_file() or marker_paths[1].is_file():
        blockers.append("source_task_active")
    if str(history.get("status") or "") in {"pending", "processing"}:
        blockers.append("source_task_active")
    if not source.with_suffix(".mp4.done").is_file():
        blockers.append("source_task_status_unknown")

    if str(state.get("review_state") or "") not in {"review_complete", "trash_pending"}:
        if not _expired_forced(state, options, now=now):
            blockers.append("review_incomplete")
    if str(state.get("review_state") or "") == "processing":
        blockers.append("source_state_active")

    current_job_id = str(options.get("_job_id") or "")
    active_recording = find_active_recording_job(root, task_id)
    if active_recording and str(active_recording.get("job_id") or "") != current_job_id:
        blockers.append("trash_action_active")
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("segment_id") or "")
        if not segment_id:
            blockers.append("segment_id_missing")
            continue
        active = find_active_segment_job(root, segment_id)
        if active is not None:
            blockers.append(f"segment_action_active:{segment_id}")
        action_state = segment.get("action_state")
        if isinstance(action_state, dict) and str(action_state.get("status") or "") in {
            "pending",
            "processing",
        }:
            blockers.append(f"segment_action_state_active:{segment_id}")
        final_item = (
            segment.get("artifacts", {}).get("final_output")
            if isinstance(segment.get("artifacts"), dict)
            else None
        )
        final_rel_path = (
            str(final_item.get("rel_path") or "")
            if isinstance(final_item, dict)
            else ""
        )
        recorded_upload_status = str(segment.get("upload_status") or "")
        upload_status_requires_row = recorded_upload_status in {
            "awaiting_publish",
            "staged",
            "queued",
            "uploading",
            "uploaded",
            "publishing",
            "published",
            "failed",
        }
        if upload_status_requires_row and final_rel_path and not Path(
            upload_conn.DATA_BASE_FILE
        ).is_file():
            blockers.append("upload_status_unknown")
        for path in _segment_paths(root, segment):
            if not Path(upload_conn.DATA_BASE_FILE).is_file():
                if upload_status_requires_row:
                    blockers.append("upload_status_unknown")
                break
            try:
                item = get_upload_item(str(path))
            except Exception:
                if upload_status_requires_row:
                    blockers.append("upload_status_unknown")
                continue
            if item and str(item.get("status") or "") in _ACTIVE_UPLOAD_STATUSES:
                blockers.append(f"upload_active:{segment_id}")
            if (
                final_rel_path
                and path == (root / final_rel_path).resolve()
                and upload_status_requires_row
                and item is None
            ):
                blockers.append(f"upload_status_unknown:{segment_id}")

    files, final_paths, missing_explicit = _resolve_package_files(
        root,
        source,
        history,
    )
    blockers.extend(missing_explicit)
    if any(path in final_paths for path in files):
        blockers.append("final_output_in_trash_plan")
    if not files:
        blockers.append("source_package_empty")
    if blockers:
        # Preserve order while avoiding noisy duplicate reasons from multiple
        # segments sharing one active state.
        unique = list(dict.fromkeys(blockers))
        raise RecordingTrashBlocked(
            "源录播暂不能回收",
            blockers=unique,
        )
    return {
        "status": "ready",
        "task_id": task_id,
        "source_rel_path": source.relative_to(root).as_posix(),
        "files": [path.relative_to(root).as_posix() for path in files],
        "blockers": [],
    }


def trash_recording(
    videos_root: str | Path,
    task_id: str,
    *,
    payload: dict[str, Any] | None = None,
    mover: Callable[[list[Path]], None] | None = None,
) -> dict[str, Any]:
    """Move one verified source package to the Windows Recycle Bin."""
    root = Path(videos_root).expanduser().resolve()
    plan = build_trash_plan(root, task_id, payload=payload)
    if plan["status"] == "already_trashed":
        return {**plan, "idempotent": True}

    relative_files = [str(path) for path in plan["files"]]
    files = [(root / relative).resolve() for relative in relative_files]
    move = mover or move_to_recycle_bin
    try:
        move(files)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        set_trash_job_state(root, task_id, status="failed", reason=reason)
        raise

    append_trash_log(
        root,
        {
            "task_id": task_id,
            "source_rel_path": plan.get("source_rel_path", ""),
            "files": relative_files,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )

    source_rel_path = str(plan.get("source_rel_path") or "")
    room_id = Path(source_rel_path).parent.name
    mutate_recording_state(
        root,
        task_id,
        lambda state: {
            **state,
            "review_state": "trash_pending",
            "trash_status": "done",
            "trash_block_reason": "",
            "trash_files": relative_files,
            "trash_completed_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
        },
        source_rel_path=source_rel_path,
        room_id=room_id,
    )
    return {
        "status": "trashed",
        "task_id": task_id,
        "files": relative_files,
        "idempotent": False,
    }


def move_to_recycle_bin(paths: list[Path]) -> None:
    """Use SHFileOperationW with FOF_ALLOWUNDO; never permanently delete."""
    if os.name != "nt":
        raise RuntimeError("Windows Recycle Bin is only available on Windows")
    existing = [path for path in paths if path.is_file()]
    if len(existing) != len(paths):
        raise FileNotFoundError("source package changed before recycle-bin move")
    if not existing:
        raise FileNotFoundError("source package is empty")

    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.UINT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # FO_DELETE + FOF_ALLOWUNDO is the shell API's undoable delete.
    source_buffer = ctypes.create_unicode_buffer(
        "\0".join(str(path) for path in existing) + "\0\0"
    )
    operation = SHFILEOPSTRUCTW(
        None,
        0x0003,
        ctypes.cast(source_buffer, wintypes.LPCWSTR),
        None,
        0x0040 | 0x0010 | 0x0004 | 0x0400,
        False,
        None,
        None,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        raise OSError(f"SHFileOperationW failed with code {result}")


def _resolve_package_files(
    root: Path,
    source: Path,
    history: dict[str, Any],
) -> tuple[list[Path], set[Path], list[str]]:
    files: set[Path] = set()
    final_paths: set[Path] = set()

    def add(path: Path, *, final: bool = False) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise RecordingTrashBlocked(
                "任务历史包含 Videos 目录外文件",
                blockers=["path_outside_videos"],
            )
        if final:
            final_paths.add(resolved)
            files.discard(resolved)
        elif resolved not in final_paths and resolved.is_file():
            files.add(resolved)

    add(source)
    for suffix in (".flv", *_SOURCE_SIDECAR_SUFFIXES, *[".mp4.task.json"]):
        add(source.with_suffix(suffix))
    for suffix in _MARKER_SUFFIXES:
        add(source.with_suffix(suffix))

    for raw in history.get("segments") or []:
        if not isinstance(raw, dict):
            continue
        artifacts = raw.get("artifacts")
        if isinstance(artifacts, dict):
            for name, item in artifacts.items():
                if not isinstance(item, dict) or not item.get("rel_path"):
                    continue
                path = (root / str(item["rel_path"])).resolve()
                add(path, final=name == "final_output")

        candidate = _history_path(root, raw.get("candidate_rel_path"), raw.get("candidate_path"))
        if candidate is not None:
            final_candidate = candidate in final_paths or _candidate_is_final(raw)
            add(candidate, final=final_candidate)
            if not final_candidate and str(raw.get("manual_origin") or "") == "missed_segment":
                for suffix in _CANDIDATE_SIDECAR_SUFFIXES:
                    add(candidate.with_name(candidate.stem + suffix) if suffix.startswith("_") else candidate.with_suffix(suffix))

    for raw in history.get("temporary_files") or []:
        path = _history_path(root, raw, None)
        if path is not None:
            add(path)

    for raw in history.get("output_slices") or []:
        path = _history_path(root, raw, None)
        if path is not None and not _path_is_final_from_history(root, path, history):
            add(path)

    # MiMo candidate records retain the generated context-window path even
    # when no publishable clip was returned.  Those files are intermediate
    # source-package material and must not be left behind by cleanup.
    for raw in history.get("candidate_judgments") or []:
        if not isinstance(raw, dict):
            continue
        path = _history_path(
            root,
            raw.get("candidate_rel_path"),
            raw.get("candidate_path"),
        )
        if path is None:
            continue
        final_candidate = _path_is_final_from_history(root, path, history)
        add(path, final=final_candidate)
        if not final_candidate:
            for suffix in _CANDIDATE_SIDECAR_SUFFIXES:
                sidecar = (
                    path.with_name(path.stem + suffix)
                    if suffix.startswith("_")
                    else path.with_suffix(suffix)
                )
                add(sidecar)

    missing_explicit: list[str] = []
    # A recorded final output is a protected boundary even if it no longer
    # exists: it must never be inferred back into a deletion set.
    for path in final_paths:
        files.discard(path)
    return sorted(files), final_paths, missing_explicit


def _history_path(root: Path, relative: Any, absolute: Any) -> Path | None:
    text = str(relative or "").strip()
    if text:
        return (root / text).resolve()
    text = str(absolute or "").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def _candidate_is_final(segment: dict[str, Any]) -> bool:
    if str(segment.get("upload_status") or "") in {
        "awaiting_publish",
        "staged",
        "queued",
        "uploading",
        "uploaded",
        "publishing",
        "published",
    }:
        return True
    return bool(segment.get("finalized_at"))


def _path_is_final_from_history(
    root: Path,
    path: Path,
    history: dict[str, Any],
) -> bool:
    for raw in history.get("segments") or []:
        if not isinstance(raw, dict):
            continue
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        item = artifacts.get("final_output")
        if isinstance(item, dict) and str(item.get("rel_path") or ""):
            if path == (root / str(item["rel_path"])).resolve():
                return True
    return False


def _segment_paths(root: Path, segment: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    artifacts = segment.get("artifacts")
    if isinstance(artifacts, dict):
        for item in artifacts.values():
            if isinstance(item, dict) and item.get("rel_path"):
                paths.append((root / str(item["rel_path"])).resolve())
    candidate = _history_path(root, segment.get("candidate_rel_path"), segment.get("candidate_path"))
    if candidate is not None:
        paths.append(candidate)
    return paths


def _expired_forced(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    now: float | None = None,
) -> bool:
    if not bool(payload.get("force_expired")):
        return False
    deadline = str(state.get("retention_deadline") or "")
    if not deadline:
        return False
    try:
        deadline_at = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = datetime.fromtimestamp(
        time.time() if now is None else float(now),
        timezone.utc,
    )
    return current >= deadline_at
