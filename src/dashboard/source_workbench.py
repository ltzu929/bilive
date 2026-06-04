"""Read model for the source-recording slice workbench."""

from __future__ import annotations

import base64
from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List

from src.autoslice.auto_slice_video.autosv.slice.slice_video import slice_video
from src.autoslice.danmaku_slice import (
    extract_danmaku_text,
    extract_timestamps_from_xml,
    format_seconds_for_filename,
)
from src.autoslice.title_generator import generate_title
from src.burn.task_history import read_task_history
from src.dashboard.task_state import build_task_inventory, resolve_task_id
from src.db.conn import insert_upload_queue
from src.upload.slice_metadata import write_slice_upload_metadata


SUMMARY_KEYS = ("keep", "manual_keep", "judge_failed", "drop", "review")


def build_source_recording_list(
    videos_root: str | Path,
    room_names: dict[str, str] | None = None,
    room_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return source recordings with segment summary counts."""
    root = Path(videos_root).expanduser().resolve()
    names = room_names or {}
    items: list[dict[str, Any]] = []
    for task in build_task_inventory(root, room_id=room_id):
        source = root / task["source_rel_path"]
        history = read_task_history(source) or {}
        segments = _normalize_segments(root, source, history.get("segments") or [])
        counts = _summary_counts(segments)
        items.append(
            {
                **task,
                "room_name": names.get(task["room_id"], task.get("room_name") or task["room_id"]),
                "source_media_id": _media_id(root, source),
                "segment_count": len(segments),
                "summary_counts": counts,
                "judge_failed_count": counts["judge_failed"],
            }
        )
    return sorted(items, key=lambda item: item.get("updated_at") or 0, reverse=True)


def build_source_recording_detail(
    videos_root: str | Path,
    task_id: str,
    room_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return one source recording with density points and candidate segments."""
    root = Path(videos_root).expanduser().resolve()
    source = resolve_task_id(root, task_id)
    tasks = build_task_inventory(root, room_id=source.parent.name)
    task = next((item for item in tasks if item["task_id"] == task_id), None)
    if task is None:
        source_rel = source.relative_to(root).as_posix()
        task = {
            "task_id": task_id,
            "room_id": source.parent.name,
            "room_name": source.parent.name,
            "source_name": source.name,
            "source_rel_path": source_rel,
            "status": "unknown",
            "source_size_mb": round(source.stat().st_size / (1024 * 1024), 1),
            "updated_at": source.stat().st_mtime,
            "message": "",
        }

    history = read_task_history(source) or {}
    segments = _normalize_segments(root, source, history.get("segments") or [])
    counts = _summary_counts(segments)
    names = room_names or {}

    return {
        **task,
        "room_name": names.get(task["room_id"], task.get("room_name") or task["room_id"]),
        "source_media_id": _media_id(root, source),
        "density_points": build_density_points(source.with_suffix(".xml")),
        "segments": segments,
        "segment_count": len(segments),
        "summary_counts": counts,
        "judge_failed_count": counts["judge_failed"],
        "history_status": history.get("status", ""),
    }


def build_density_points(xml_path: str | Path, window_seconds: int = 10) -> list[dict[str, Any]]:
    """Aggregate danmaku timestamps into fixed-width density windows."""
    timestamps = extract_timestamps_from_xml(str(xml_path))
    if not timestamps:
        return []

    buckets: Counter[int] = Counter()
    for timestamp in timestamps:
        if timestamp < 0:
            continue
        start = int(timestamp // window_seconds) * window_seconds
        buckets[start] += 1

    if not buckets:
        return []

    max_count = max(buckets.values())
    points: list[dict[str, Any]] = []
    for start in sorted(buckets):
        count = buckets[start]
        points.append(
            {
                "start_seconds": start,
                "end_seconds": start + window_seconds,
                "count": count,
                "normalized": round(count / max_count, 4) if max_count else 0.0,
            }
        )
    return points


def manual_keep_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a candidate as manually kept and queue it for upload."""
    data = payload or {}

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        _apply_optional_metadata(segment, data)
        _apply_optional_range(segment, data)
        candidate = _segment_candidate_path(root, segment)
        if not candidate.is_file():
            raise FileNotFoundError(f"Candidate not found: {candidate}")
        segment["judge_status"] = "manual_keep"
        segment["manual_override"] = True
        segment["upload_status"] = "queued"
        write_slice_upload_metadata(
            candidate,
            title=str(segment.get("title") or candidate.stem),
            desc=str(segment.get("description") or ""),
            tag=segment.get("tags") or ["直播切片"],
        )
        insert_upload_queue(str(candidate))
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def drop_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a candidate as dropped without deleting the retained review file."""
    data = payload or {}

    def mutate(_root: Path, _source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        segment["judge_status"] = "drop"
        segment["upload_status"] = "not_queued"
        segment["manual_override"] = True
        reason = str(data.get("reason") or "").strip()
        if reason:
            segment["quality_reason"] = reason
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def update_segment_range(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Update the source-time range for a segment."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    if "start_seconds" not in payload or "end_seconds" not in payload:
        raise ValueError("start_seconds and end_seconds are required")
    start = _float(payload.get("start_seconds"))
    end = _float(payload.get("end_seconds"))
    if end <= start:
        raise ValueError("end_seconds must be greater than start_seconds")

    def mutate(_root: Path, _source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        segment["start_seconds"] = start
        segment["end_seconds"] = end
        segment["manual_override"] = True
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def retry_segment_judge(videos_root: str | Path, segment_id: str) -> dict[str, Any]:
    """Run LLM judging again for a retained candidate clip."""

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        candidate = _segment_candidate_path(root, segment)
        if not candidate.is_file():
            raise FileNotFoundError(f"Candidate not found: {candidate}")
        start = _float(segment.get("start_seconds"))
        end = _float(segment.get("end_seconds"))
        danmaku_text = extract_danmaku_text(str(source.with_suffix(".xml")), start, end)
        result = generate_title(
            str(candidate),
            source.parent.name,
            danmaku_text=danmaku_text,
        )
        segment["judge_status"] = result.judge_status or (
            "keep" if result.retain_recommendation else "drop"
        )
        segment["judge_error"] = result.judge_error
        segment["quality_score"] = result.quality_score
        segment["quality_reason"] = result.quality_reason
        segment["title"] = result.title
        segment["description"] = result.description
        segment["tags"] = result.tags
        segment["manual_override"] = False
        segment["upload_status"] = "not_queued"
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def render_segment(videos_root: str | Path, segment_id: str) -> dict[str, Any]:
    """Regenerate the candidate clip from the segment's current source range."""

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        start = _float(segment.get("start_seconds"))
        end = _float(segment.get("end_seconds"))
        if end <= start:
            raise ValueError("end_seconds must be greater than start_seconds")
        output = source.with_name(f"{format_seconds_for_filename(start)}s_{source.name}")
        slice_video(source, output, start, end - start)
        segment["candidate_path"] = str(output)
        segment["candidate_rel_path"] = output.relative_to(root).as_posix()
        segment["candidate_media_id"] = _media_id(root, output)
        segment["manual_override"] = True
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def _normalize_segments(root: Path, source: Path, segments: Any) -> list[dict[str, Any]]:
    if not isinstance(segments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        segment = dict(raw)
        segment.setdefault("source_rel_path", source.relative_to(root).as_posix())
        segment.setdefault("candidate_rel_path", _candidate_rel_path(root, segment))
        segment.setdefault("candidate_media_id", _candidate_media_id(root, segment))
        segment.setdefault("judge_status", "review")
        segment.setdefault("judge_error", "")
        segment.setdefault("upload_status", "not_queued")
        segment.setdefault("manual_override", False)
        for key in ("start_seconds", "end_seconds", "density_core_start", "density_core_end"):
            if key in segment:
                segment[key] = _float(segment.get(key))
        normalized.append(segment)
    return normalized


def _mutate_segment(
    videos_root: str | Path,
    segment_id: str,
    mutator,
) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    for task in build_task_inventory(root):
        source = root / task["source_rel_path"]
        history_path = source.with_suffix(".mp4.task.json")
        if not history_path.is_file():
            continue
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        segments = history.get("segments")
        if not isinstance(segments, list):
            continue
        for index, raw in enumerate(segments):
            if not isinstance(raw, dict) or raw.get("segment_id") != segment_id:
                continue
            segment = dict(raw)
            updated = mutator(root, source, segment)
            segments[index] = updated
            _write_history(history_path, history)
            return _normalize_segments(root, source, [updated])[0]
    raise FileNotFoundError(f"Segment not found: {segment_id}")


def _write_history(path: Path, history: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".task.json.tmp")
    tmp_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _apply_optional_metadata(segment: dict[str, Any], payload: dict[str, Any]) -> None:
    if "title" in payload:
        segment["title"] = str(payload.get("title") or "").strip()
    if "description" in payload:
        segment["description"] = str(payload.get("description") or "")
    if "tags" in payload:
        tags = payload.get("tags")
        if isinstance(tags, list):
            segment["tags"] = [str(item).strip() for item in tags if str(item).strip()]
        else:
            segment["tags"] = [str(tags).strip()] if str(tags).strip() else []


def _apply_optional_range(segment: dict[str, Any], payload: dict[str, Any]) -> None:
    if "start_seconds" not in payload and "end_seconds" not in payload:
        return
    start = _float(payload.get("start_seconds", segment.get("start_seconds")))
    end = _float(payload.get("end_seconds", segment.get("end_seconds")))
    if end <= start:
        raise ValueError("end_seconds must be greater than start_seconds")
    segment["start_seconds"] = start
    segment["end_seconds"] = end


def _segment_candidate_path(root: Path, segment: dict[str, Any]) -> Path:
    rel = _candidate_rel_path(root, segment)
    if rel:
        return (root / rel).resolve()
    candidate = Path(str(segment.get("candidate_path") or "")).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Candidate path is outside Videos root") from None
    return candidate


def _summary_counts(segments: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in SUMMARY_KEYS}
    for segment in segments:
        status = str(segment.get("judge_status") or "review")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _candidate_rel_path(root: Path, segment: dict[str, Any]) -> str:
    rel = str(segment.get("candidate_rel_path") or "")
    if rel:
        return rel.replace("\\", "/")
    path_text = str(segment.get("candidate_path") or "")
    if not path_text:
        return ""
    try:
        return Path(path_text).resolve().relative_to(root).as_posix()
    except ValueError:
        return ""


def _candidate_media_id(root: Path, segment: dict[str, Any]) -> str:
    rel = _candidate_rel_path(root, segment)
    if not rel:
        return ""
    candidate = (root / rel).resolve()
    if not candidate.is_file():
        return ""
    return _media_id(root, candidate)


def _media_id(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root).as_posix()
    return base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
