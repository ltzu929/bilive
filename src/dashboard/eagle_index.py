"""Read model for Eagle's lightweight source-recording mirror."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


_SOURCE_NAME_RE = re.compile(
    r"^(?P<room>\d+)_(?P<date>\d{8})-(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})(?:_\(\d+\))?\.mp4$"
)

# Process-level cover cache so repeated Eagle polls do not re-hit the Bilibili
# live-room API (and block) for every room on every request. Empty results are
# cached too, with the same TTL, to avoid hammering rooms that have no cover.
_COVER_TTL_SECONDS = 300.0
_cover_cache: dict[str, tuple[float, str]] = {}


def build_eagle_source_index(
    videos_root: str | Path,
    *,
    room_names: dict[str, str] | None = None,
    room_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return current source recordings formatted for Eagle plugin sync."""
    # Imported lazily so the Pi dashboard can boot without the Windows-only
    # autoslice dependencies (pysrt/openai/faster_whisper) that
    # source_workbench pulls in at module top level.
    from src.dashboard.source_workbench import build_source_recording_list

    recordings = build_source_recording_list(
        videos_root,
        room_names=room_names,
        room_id=room_id,
    )
    return [_eagle_item(recording) for recording in recordings]


def _eagle_item(recording: dict[str, Any]) -> dict[str, Any]:
    counts = recording.get("summary_counts") or {}
    task_id = str(recording.get("task_id") or "")
    source_name = str(recording.get("source_name") or "")
    room_id = str(recording.get("room_id") or "")

    return {
        "source_task_id": task_id,
        "source_rel_path": str(recording.get("source_rel_path") or ""),
        "source_name": source_name,
        "room_id": room_id,
        "room_name": str(recording.get("room_name") or recording.get("room_id") or ""),
        "recorded_at": _recorded_at(source_name),
        "source_size_mb": float(recording.get("source_size_mb") or 0.0),
        "status": str(recording.get("status") or ""),
        "segment_count": int(recording.get("segment_count") or 0),
        "review_count": int(counts.get("review") or 0) + int(counts.get("judge_failed") or 0),
        "keep_count": int(counts.get("keep") or 0) + int(counts.get("manual_keep") or 0),
        "thumbnail_url": _cached_cover(room_id),
        "workspace_url": f"/tasks?source_task_id={task_id}",
    }


def fetch_live_room_cover(room_id: str, *, timeout: float = 1.5) -> str:
    """Fetch the current Bilibili live room cover URL, returning empty on failure."""
    if not room_id:
        return ""
    url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
    request = Request(url, headers={"User-Agent": "bilive-dashboard/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return ""
    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        return ""
    data = payload["data"]
    for key in ("user_cover", "cover", "keyframe"):
        value = str(data.get(key) or "").strip()
        if value:
            return _normalize_url(value)
    return ""


def _cached_cover(room_id: str) -> str:
    if not room_id:
        return ""
    now = time.monotonic()
    entry = _cover_cache.get(room_id)
    if entry is not None and now - entry[0] < _COVER_TTL_SECONDS:
        return entry[1]
    cover = fetch_live_room_cover(room_id)
    _cover_cache[room_id] = (now, cover)
    return cover


def _normalize_url(value: str) -> str:
    if value.startswith("//"):
        return f"https:{value}"
    return value


def _recorded_at(source_name: str) -> str:
    match = _SOURCE_NAME_RE.match(source_name)
    if not match:
        return ""
    raw_date = match.group("date")
    return (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]} "
        f"{match.group('hour')}:{match.group('minute')}:{match.group('second')}"
    )
