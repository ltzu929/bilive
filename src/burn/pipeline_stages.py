"""Independently testable stages used by the slice pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.autoslice.analysis_result import AnalysisResult


ACTIVE_UPLOAD_STATUSES = {
    "queued",
    "uploading",
    "uploaded",
    "publishing",
    "published",
}


def analyze_stage(
    video_path: str,
    *,
    artist: str,
    danmaku_text: str,
    analyzer: Callable[..., Any],
) -> AnalysisResult:
    result = analyzer(video_path, artist, danmaku_text=danmaku_text)
    if not isinstance(result, AnalysisResult):
        raise TypeError("candidate analyzer must return AnalysisResult")
    return result


def subtitle_stage(
    video_path: str,
    analysis: AnalysisResult,
    *,
    burner: Callable[..., Any],
) -> dict[str, Any]:
    try:
        result = burner(video_path, analysis)
    except Exception as exc:
        return {"ok": False, "error": f"Subtitle burn failed: {exc}"}
    if not bool(getattr(result, "burned", False)):
        message = str(getattr(result, "message", "") or "unknown error")
        return {"ok": False, "error": f"Subtitle burn failed: {message}"}
    return {"ok": True, "error": ""}


def metadata_stage(
    video_path: str,
    analysis: AnalysisResult,
    *,
    room_id: str,
    writer: Callable[..., Any],
) -> dict[str, Any]:
    try:
        writer(
            video_path,
            title=analysis.title,
            desc=analysis.description,
            tag=analysis.tags,
            source=f"https://live.bilibili.com/{room_id}",
        )
    except Exception as exc:
        return {"ok": False, "error": f"Upload metadata failed: {exc}"}
    return {"ok": True, "error": ""}


def enqueue_stage(
    video_path: str,
    *,
    insert: Callable[[str], Any],
    lookup: Callable[[str], Any],
    skip: bool = False,
) -> dict[str, Any]:
    if skip:
        return {
            "ok": True,
            "status": "skipped",
            "created": False,
            "error": "",
        }

    try:
        queued = bool(insert(video_path))
    except Exception as exc:
        queued = False
        queue_error = str(exc)
    else:
        queue_error = "queue insert returned false"

    if queued:
        return {
            "ok": True,
            "status": "queued",
            "created": True,
            "error": "",
        }

    existing = lookup(video_path)
    existing_status = (
        str(existing.get("status") or "")
        if isinstance(existing, dict)
        else ""
    )
    if existing_status in ACTIVE_UPLOAD_STATUSES:
        return {
            "ok": True,
            "status": existing_status,
            "created": False,
            "error": "",
        }
    return {
        "ok": False,
        "status": existing_status or "not_queued",
        "created": False,
        "error": f"Upload queue failed: {queue_error}",
    }
