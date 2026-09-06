"""Read model for the source-recording slice workbench."""

from __future__ import annotations

import base64
from functools import wraps
from src.server.action_jobs import action_submission_lock
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List
import uuid

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.autoslice.danmaku_slice import (
    extract_timestamps_from_xml,
    format_seconds_for_filename,
)
from src.burn.task_history import lock_task_history, read_task_history
from src.dashboard.task_state import build_task_inventory, resolve_task_id, _build_task
from src.dashboard.errors import SegmentStateConflict
from src.dashboard.source_lifecycle import (
    MISSED_SEGMENT_REASONS,
    UNRESOLVED_STATUSES,
    build_lifecycle_view,
    profile_context_for_mimo,
    read_recording_state,
    record_review_experiences,
    record_technical_experience,
    read_streamer_profile,
    profile_subtitle_style,
    set_review_state,
)
from src.db.conn import (
    activate_staged_upload,
    withdraw_staged_upload,
    delete_upload_queue,
    get_upload_item,
    insert_upload_queue,
    requeue_failed_upload,
    stage_upload_queue,
)
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    write_slice_upload_metadata,
)


SUMMARY_KEYS = ("keep", "manual_keep", "judge_failed", "drop", "review")


def _review_write(function):
    @wraps(function)
    def locked(videos_root, *args, **kwargs):
        with action_submission_lock(videos_root):
            return function(videos_root, *args, **kwargs)
    return locked


def _task_id_for_source(source: Path, root: Path) -> str:
    return (
        base64.urlsafe_b64encode(
            source.relative_to(root).as_posix().encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )


class SegmentFinalizeError(RuntimeError):
    """Recoverable finalization error persisted on both segment and job."""

    def __init__(self, failure: dict[str, str]) -> None:
        self.failure = failure
        super().__init__(failure["summary"])


def extract_danmaku_text(*args, **kwargs):
    from src.autoslice.danmaku_slice import extract_danmaku_text as extract

    return extract(*args, **kwargs)


def analyze_candidate(*args, **kwargs):
    from src.autoslice.candidate_analyzer import analyze_candidate as analyze

    return analyze(*args, **kwargs)


def slice_video(*args, **kwargs):
    from src.autoslice.danmaku_slice import slice_video as render
    return render(*args, **kwargs)


def transcribe_segment_audio(video_path: str, duration_seconds: float, *, start_seconds: float = 0.0) -> dict[str, Any]:
    """Run the configured ASR for one already-trimmed raw artifact."""
    from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio
    from src.config import (
        MULTI_MODAL_WHISPER_MODEL,
        WHISPER_COMPUTE_TYPE,
        WHISPER_DEVICE,
    )

    return analyze_audio(
        video_path,
        MULTI_MODAL_WHISPER_MODEL,
        whisper_device=WHISPER_DEVICE,
        whisper_compute_type=WHISPER_COMPUTE_TYPE,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )


def burn_final_subtitles(
    raw_path: Path,
    analysis: AnalysisResult,
    output_path: Path,
    style,
    *, source_range=None,
):
    from src.burn.subtitle_burn import burn_subtitles_from_analysis

    return burn_subtitles_from_analysis(
        raw_path,
        analysis,
        output_path=output_path,
        style=style,
        source_range=source_range,
    )


def build_source_recording_list(
    videos_root: str | Path,
    room_names: dict[str, str] | None = None,
    room_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return source recordings with segment summary counts."""
    root = Path(videos_root).expanduser().resolve()
    names = room_names or {}
    items: list[dict[str, Any]] = []
    for task in build_task_inventory(root, room_id=room_id, include_history=True):
        source = root / task["source_rel_path"]
        history = task.pop("_history")
        segments = _normalize_segments(root, source, history.get("segments") or [])
        counts = _summary_counts(segments)
        lifecycle = build_lifecycle_view(root, task, history, segments)
        profile = read_streamer_profile(root, task["room_id"])
        room_name = str(profile.get("display_name") or "").strip() or names.get(
            task["room_id"], task.get("room_name") or task["room_id"]
        )
        items.append(
            {
                **task,
                "room_name": room_name,
                "recorded_at": _recorded_at(task.get("source_name") or ""),
                "source_media_id": _media_id(root, source),
                "segment_count": len(segments),
                "summary_counts": counts,
                "judge_failed_count": counts["judge_failed"],
                **lifecycle,
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
    task = _build_task(source, source.parent, root, include_history=True)
    history = task.pop("_history")
    segments = _normalize_segments(root, source, history.get("segments") or [])
    _apply_display_defaults(root, source, segments)
    counts = _summary_counts(segments)
    names = room_names or {}
    lifecycle = build_lifecycle_view(root, task, history, segments)
    profile = read_streamer_profile(root, task["room_id"])
    room_name = str(profile.get("display_name") or "").strip() or names.get(
        task["room_id"], task.get("room_name") or task["room_id"]
    )

    return {
        **task,
        "room_name": room_name,
        "recorded_at": _recorded_at(task.get("source_name") or ""),
        "source_media_id": _media_id(root, source),
        "density_points": build_density_points(source.with_suffix(".xml")),
        "segments": segments,
        "candidate_judgments": history.get("candidate_judgments") or [],
        "segment_count": len(segments),
        "summary_counts": counts,
        "judge_failed_count": counts["judge_failed"],
        "history_status": history.get("status", ""),
        **lifecycle,
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


@_review_write
def manual_keep_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a candidate as manually kept without exposing it to upload."""
    data = payload or {}

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        _ensure_unpublished(root, segment)
        _apply_optional_metadata(segment, data)
        _apply_optional_range(segment, data)
        if not _preview_allowed(segment):
            raise ValueError("内部候选没有可发布预览，请先调整边界并生成成片")
        candidate = _segment_candidate_path(root, segment)
        if not candidate.is_file():
            raise FileNotFoundError(f"Candidate not found: {candidate}")
        segment["judge_status"] = "manual_keep"
        segment["manual_override"] = True
        segment["preview_available"] = True
        segment["preview_reason"] = ""
        # A manually kept item is still only an internal candidate.  Upload
        # metadata belongs to the finalization step, immediately before the
        # staged queue row is created.
        segment["upload_status"] = "not_queued"
        segment.pop("upload_error", None)
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


_PUBLISHING_UPLOAD_STATUSES = {
    "queued",
    "uploading",
    "uploaded",
    "publishing",
    "published",
}


def _ensure_unpublished(root: Path, segment: dict[str, Any]) -> None:
    """Protect both canonical and historical candidate-as-final records."""
    if segment.get("publish_approval") == "approved":
        raise SegmentStateConflict("成片已经允许发布；请创建新的人工候选")
    status = str(segment.get("upload_status") or "not_queued")
    if status in _PUBLISHING_UPLOAD_STATUSES or status == "failed":
        raise SegmentStateConflict("成片已进入发布流程，不能覆盖")
    paths = {_candidate_rel_path(root, segment)}
    paths.add(str((segment.get("artifacts") or {}).get("final_output", {}).get("rel_path") or ""))
    for rel in paths - {""}:
        try:
            item = get_upload_item(str(_artifact_path(root, rel)))
        except Exception as exc:
            if status not in {"", "not_queued", "skipped"}:
                raise SegmentStateConflict("无法确认上传状态，已停止修改") from exc
            continue
        if item and (item.get("status") != "staged" or item.get("remote_filename")):
            raise SegmentStateConflict("成片已进入发布流程，不能覆盖")


def _invalidate_final_output(root: Path, segment: dict[str, Any]) -> bool:
    """Clear an unapproved final when a review edit needs regeneration."""
    _ensure_unpublished(root, segment)
    artifacts = segment.get("artifacts")
    if not isinstance(artifacts, dict):
        return False
    final_item = artifacts.get("final_output")
    if not isinstance(final_item, dict) or not final_item.get("rel_path"):
        return False

    final_rel = str(final_item["rel_path"])
    final_path = _artifact_path(root, final_rel)
    recorded_status = str(segment.get("upload_status") or "not_queued")
    try:
        queue_item = get_upload_item(str(final_path))
    except Exception as exc:
        if recorded_status in {"awaiting_publish", "staged", *_PUBLISHING_UPLOAD_STATUSES}:
            raise SegmentStateConflict(
                "无法确认成片上传状态，已停止修改；请先检查上传数据库"
            ) from exc
        queue_item = None

    if queue_item is None:
        if recorded_status in {"awaiting_publish", "staged", *_PUBLISHING_UPLOAD_STATUSES}:
            raise SegmentStateConflict("无法确认成片上传状态，已停止修改")
    else:
        queue_status = str(queue_item.get("status") or "")
        if queue_status in _PUBLISHING_UPLOAD_STATUSES:
            raise SegmentStateConflict(
                "成片已进入上传或发布流程，不能覆盖；请创建新的人工候选"
            )
        if queue_status not in {"staged", "failed"}:
            raise SegmentStateConflict(
                f"成片当前处于 {queue_status or '未知'} 状态，不能覆盖"
            )
        if not withdraw_staged_upload(str(final_path)):
            raise SegmentStateConflict("无法安全撤销成片的等待确认队列项")
        delete_slice_upload_metadata(final_path)

    previous_outputs = segment.get("final_output_history")
    if not isinstance(previous_outputs, list):
        previous_outputs = []
    if final_rel not in previous_outputs:
        previous_outputs.append(final_rel)
    segment["final_output_history"] = previous_outputs
    updated_artifacts = dict(artifacts)
    updated_artifacts.pop("final_output", None)
    segment["artifacts"] = updated_artifacts
    if _candidate_rel_path(root, segment) == final_rel:
        segment.pop("candidate_path", None)
        segment.pop("candidate_rel_path", None)
        segment.pop("candidate_media_id", None)
    segment["preview_available"] = False
    segment["preview_reason"] = "区间或字幕样式已修改，请重新生成最终成片"
    segment["upload_status"] = "not_queued"
    segment["publish_approval"] = ""
    segment.pop("publish_approved_at", None)
    return True


@_review_write
def prepare_segment_finalize(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Persist lightweight review edits before queueing Windows finalization."""
    data = validate_segment_finalize_payload(payload)

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        if "expected_revision" in data and data["expected_revision"] != int(segment.get("revision") or 0):
            raise SegmentStateConflict("片段已改变，请先核对草稿与当前版本")
        _invalidate_final_output(root, segment)
        _apply_optional_metadata(segment, data)
        _apply_optional_range(segment, data)
        _apply_profile_metadata(root, source, segment, data)
        start = _float(segment.get("start_seconds"))
        end = _float(segment.get("end_seconds"))
        if end <= start:
            raise ValueError("end_seconds must be greater than start_seconds")

        from src.burn.subtitle_burn import SubtitleStyle
        from src.config import default_subtitle_style

        if "subtitle_style" in data:
            style = SubtitleStyle.from_mapping(data["subtitle_style"])
            segment["_subtitle_style_source"] = "clip"
        elif str(segment.get("_subtitle_style_source") or "") == "clip":
            style = SubtitleStyle.from_mapping(segment.get("subtitle_style"))
        else:
            profile_style = profile_subtitle_style(root, source.parent.name)
            if profile_style:
                style = SubtitleStyle.from_mapping(profile_style)
                segment["_subtitle_style_source"] = "profile"
            elif isinstance(segment.get("subtitle_style"), dict):
                style = SubtitleStyle.from_mapping(segment["subtitle_style"])
            else:
                style = default_subtitle_style()
        segment["subtitle_style"] = style.to_mapping()
        segment["artifacts"] = _artifact_plan(root, source, segment)
        segment["manual_override"] = True
        segment["upload_status"] = "not_queued"
        segment["publish_approval"] = ""
        segment.pop("publish_approved_at", None)
        segment["failure"] = None
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def validate_segment_finalize_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate and normalize review edits without mutating task history."""
    if payload is None:
        data: dict[str, Any] = {}
    elif isinstance(payload, dict):
        data = dict(payload)
    else:
        raise ValueError("request body must be an object")
    if "start" in data and "start_seconds" not in data:
        data["start_seconds"] = data["start"]
    if "end" in data and "end_seconds" not in data:
        data["end_seconds"] = data["end"]
    for key in ("start_seconds", "end_seconds"):
        if key not in data:
            continue
        try:
            value = float(data[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if not math.isfinite(value):
            raise ValueError(f"{key} must be finite")
        if key == "start_seconds" and value < 0:
            raise ValueError("start_seconds must be non-negative")
        if key == "end_seconds" and value < 0:
            raise ValueError("end_seconds must be non-negative")
        data[key] = value
    if (
        "start_seconds" in data
        and "end_seconds" in data
        and data["end_seconds"] <= data["start_seconds"]
    ):
        raise ValueError("end_seconds must be greater than start_seconds")
    if "subtitle_style" in data:
        style_payload = data.get("subtitle_style")
        if not isinstance(style_payload, dict):
            raise ValueError("subtitle_style must be an object")
        from src.burn.subtitle_burn import SubtitleStyle

        data["subtitle_style"] = SubtitleStyle.from_mapping(style_payload).to_mapping()
    return data


def record_segment_action_state(
    videos_root: str | Path,
    segment_id: str,
    *,
    status: str,
    job_id: str = "",
    action: str = "finalize_segment",
    failure: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Record dashboard-visible state for an asynchronous segment action."""

    def mutate(_root: Path, _source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        previous = (
            dict(segment.get("action_state"))
            if isinstance(segment.get("action_state"), dict)
            else {}
        )
        previous.update(
            {
                "action": str(action),
                "status": str(status),
                "updated_at": _now(),
            }
        )
        if job_id:
            previous["job_id"] = str(job_id)
        segment["action_state"] = previous
        if status in {"pending", "processing"}:
            segment["failure"] = None
        elif status == "failed" and failure:
            segment["failure"] = dict(failure)
            segment["judge_status"] = "judge_failed"
            segment["judge_error"] = str(
                failure.get("summary") or "片段动作执行失败"
            )
            segment["upload_status"] = "not_queued"
        elif status == "done":
            segment["failure"] = None
        return segment

    result = _mutate_segment(videos_root, segment_id, mutate, bump_revision=False)
    if status == "failed" and failure:
        try:
            _root, source, failed_segment = _read_segment(videos_root, segment_id)
            record_technical_experience(
                _root,
                room_id=source.parent.name,
                task_id=_task_id_for_source(source, _root),
                source_rel_path=source.relative_to(_root).as_posix(),
                segment=failed_segment,
                failure=failure,
                job_id=job_id,
            )
        except Exception:
            # The action state remains authoritative; failure telemetry must
            # not hide the original job result.
            pass
    return result


def finalize_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a publishable final artifact without repeating MiMo analysis.

    Raw media, ASR analysis, and the final burned output use distinct paths.
    Each successful artifact can therefore be reused when a later stage fails.
    """
    total_started = time.perf_counter()
    timings: dict[str, int] = {}
    finalize_payload = dict(payload or {})
    expected_revision = finalize_payload.pop("_expected_revision", None)
    job_id = str(finalize_payload.pop("_job_id", "") or "")
    if expected_revision is not None:
        _root, _source, current = _read_segment(videos_root, segment_id)
        current_revision = int(_float(current.get("revision")))
        same_recovered_job = bool(
            job_id
            and str(current.get("_finalize_job_id") or "") == job_id
            and int(_float(current.get("_finalize_expected_revision")))
            == int(_float(expected_revision))
        )
        if current_revision != int(_float(expected_revision)) and not same_recovered_job:
            raise SegmentStateConflict(
                "片段在任务入队后已被修改；请刷新后重新生成成片"
            )
        if job_id and not same_recovered_job:
            def mark_revision_validated(
                _root_path: Path,
                _source_path: Path,
                segment: dict[str, Any],
            ) -> dict[str, Any]:
                segment["_finalize_job_id"] = job_id
                segment["_finalize_expected_revision"] = int(
                    _float(expected_revision)
                )
                return segment

            current = _mutate_segment(
                videos_root,
                segment_id,
                mark_revision_validated,
                bump_revision=False,
            )
    prepared = (
        current
        if expected_revision is not None
        else prepare_segment_finalize(videos_root, segment_id, finalize_payload)
    )
    record_segment_action_state(
        videos_root,
        segment_id,
        status="processing",
        job_id=str((prepared.get("action_state") or {}).get("job_id") or ""),
    )
    root, source, segment = _read_segment(videos_root, segment_id)
    plan = _artifact_plan(root, source, segment)
    start = _float(segment.get("start_seconds"))
    end = _float(segment.get("end_seconds"))
    duration = end - start
    raw_path = _artifact_path(root, plan["raw_candidate"]["rel_path"])
    analysis_path = _artifact_path(root, plan["analysis_sidecar"]["rel_path"])
    final_path = _artifact_path(root, plan["final_output"]["rel_path"])

    if not _nonempty_file(raw_path):
        stage_started = time.perf_counter()
        try:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = raw_path.with_name(
                f"{raw_path.stem}.{os.getpid()}.tmp{raw_path.suffix}"
            )
            temporary.unlink(missing_ok=True)
            slice_video(source, temporary, start, duration)
            if not _nonempty_file(temporary):
                raise RuntimeError("raw candidate renderer produced no media")
            os.replace(temporary, raw_path)
        except Exception as exc:
            if "temporary" in locals():
                temporary.unlink(missing_ok=True)
            _fail_finalize(
                videos_root,
                segment_id,
                stage="raw_render",
                code="raw_render_failed",
                summary="无法生成成片所需的原始片段",
                recovery_action="检查源录播与 ffmpeg 后重试生成成片",
                exc=exc,
                plan=plan,
                timings=_finish_timing(
                    timings, "raw_render", stage_started, total_started
                ),
            )
        timings["raw_render"] = _elapsed_ms(stage_started)
    else:
        timings["raw_render"] = 0

    analysis = _load_reusable_finalize_analysis(
        root,
        segment,
        analysis_path,
        start=start,
        end=end,
    )
    analysis_reused = analysis is not None
    if analysis is None:
        stage_started = time.perf_counter()
        try:
            audio = transcribe_segment_audio(str(source), duration, start_seconds=start)
            analysis = _analysis_from_audio(segment, audio, start=start, end=end)
        except Exception as exc:
            _fail_finalize(
                videos_root,
                segment_id,
                stage="asr",
                code="asr_failed",
                summary="语音转写失败，成片未进入上传队列",
                recovery_action="确认 Whisper 模型可用后重试生成成片",
                exc=exc,
                plan=plan,
                timings=_finish_timing(timings, "asr", stage_started, total_started),
            )
        timings["asr"] = _elapsed_ms(stage_started)
    else:
        timings["asr"] = 0

    assert analysis is not None
    _apply_segment_metadata_to_analysis(analysis, segment, start=start, end=end)
    stage_started = time.perf_counter()
    try:
        _write_analysis_atomic(analysis_path, analysis)
    except Exception as exc:
        _fail_finalize(
            videos_root,
            segment_id,
            stage="analysis",
            code="analysis_write_failed",
            summary="转写结果无法保存，成片未进入上传队列",
            recovery_action="检查 Videos 目录写入权限后重试生成成片",
            exc=exc,
            plan=plan,
            timings=_finish_timing(timings, "analysis", stage_started, total_started),
        )
    timings["analysis"] = _elapsed_ms(stage_started)

    if not _nonempty_file(final_path) or not analysis_reused:
        stage_started = time.perf_counter()
        try:
            from src.burn.subtitle_burn import SubtitleStyle

            style = SubtitleStyle.from_mapping(segment.get("subtitle_style"))
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_final = final_path.with_name(
                f"{final_path.stem}.{os.getpid()}.tmp{final_path.suffix}"
            )
            temporary_final.unlink(missing_ok=True)
            burn_result = burn_final_subtitles(
                source,
                analysis,
                temporary_final,
                style,
                source_range=(start, end),
            )
            if not bool(getattr(burn_result, "burned", False)):
                raise RuntimeError(
                    str(getattr(burn_result, "message", "") or "subtitle burn failed")
                )
            if not _nonempty_file(temporary_final):
                raise RuntimeError("subtitle burner produced no final media")
            os.replace(temporary_final, final_path)
        except Exception as exc:
            if "temporary_final" in locals():
                temporary_final.unlink(missing_ok=True)
            _fail_finalize(
                videos_root,
                segment_id,
                stage="subtitle_burn",
                code="subtitle_burn_failed",
                summary="字幕烧录失败，已保留原始片段和转写结果",
                recovery_action="检查技术详情或调整字幕样式后重试生成成片",
                exc=exc,
                plan=plan,
                timings=_finish_timing(
                    timings, "subtitle_burn", stage_started, total_started
                ),
            )
        timings["subtitle_burn"] = _elapsed_ms(stage_started)
    else:
        timings["subtitle_burn"] = 0

    stage_started = time.perf_counter()
    try:
        write_slice_upload_metadata(
            final_path,
            title=str(segment.get("title") or final_path.stem),
            desc=str(segment.get("description") or ""),
            tag=_segment_tags(segment),
            source=f"https://live.bilibili.com/{source.parent.name}",
            source_task_id=_task_id_for_source(source, root),
            segment_id=segment_id,
        )
    except Exception as exc:
        _fail_finalize(
            videos_root,
            segment_id,
            stage="metadata",
            code="metadata_write_failed",
            summary="投稿元数据写入失败，成片未进入上传队列",
            recovery_action="修正标题、标签或文件权限后重试生成成片",
            exc=exc,
            plan=plan,
            timings=_finish_timing(timings, "metadata", stage_started, total_started),
        )
    timings["metadata"] = _elapsed_ms(stage_started)

    def mark_ready(
        root_path: Path,
        _source_path: Path,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        current.update(
            {
                "candidate_path": str(final_path),
                "candidate_rel_path": final_path.relative_to(root_path).as_posix(),
                "candidate_media_id": _media_id(root_path, final_path),
                "preview_available": True,
                "preview_reason": "",
                "analysis_path": str(analysis_path),
                "upload_status": "not_queued",
                "failure": None,
                "artifacts": _artifact_snapshot(root_path, plan),
                "timings_ms": dict(timings),
            }
        )
        current["action_state"] = _next_action_state(current, "processing")
        return current

    # Persist durable, reusable artifacts before exposing the media to the
    # upload consumer. If this write fails, no upload row is created.
    _mutate_segment(videos_root, segment_id, mark_ready)

    stage_started = time.perf_counter()
    try:
        if os.environ.get("BILIVE_SKIP_UPLOAD_QUEUE", "").strip() == "1":
            queue_result = {"status": "skipped", "created": False}
        else:
            queue_result = stage_upload_queue(str(final_path))
            queue_status = str(queue_result.get("status") or "")
            if queue_status not in {
                "staged",
                "queued",
                "uploading",
                "uploaded",
                "publishing",
                "published",
            }:
                raise RuntimeError(f"upload row cannot be staged from {queue_status}")
        queue_status = str(queue_result.get("status") or "")
        if queue_status == "skipped":
            upload_status = "skipped"
        elif queue_status == "staged":
            upload_status = "awaiting_publish"
        else:
            upload_status = queue_status
    except Exception as exc:
        _fail_finalize(
            videos_root,
            segment_id,
            stage="queue",
            code="upload_queue_failed",
            summary="成片已生成，但未能加入上传队列",
            recovery_action="检查上传数据库后重试；不会重新调用 MiMo 或 ASR",
            exc=exc,
            plan=plan,
            timings=_finish_timing(timings, "queue", stage_started, total_started),
        )
    timings["queue"] = _elapsed_ms(stage_started)
    timings["total"] = _elapsed_ms(total_started)

    def succeed(
        root_path: Path,
        _source_path: Path,
        current: dict[str, Any],
    ) -> dict[str, Any]:
        current.update(
            {
                "candidate_path": str(final_path),
                "candidate_rel_path": final_path.relative_to(root_path).as_posix(),
                "candidate_media_id": _media_id(root_path, final_path),
                "preview_available": True,
                "preview_reason": "",
                "analysis_path": str(analysis_path),
                "judge_status": "manual_keep",
                "judge_error": "",
                "manual_override": True,
                "upload_status": upload_status,
                "failure": None,
                "artifacts": _artifact_snapshot(root_path, plan),
                "timings_ms": dict(timings),
            }
        )
        current["action_state"] = _next_action_state(current, "done")
        return current

    try:
        completed = _mutate_segment(videos_root, segment_id, succeed)
    except Exception:
        if bool(queue_result.get("created")):
            delete_upload_queue(str(final_path))
        raise

    return completed


@_review_write
def approve_publish_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Activate one staged final artifact after an explicit human approval."""
    root, _source, segment = _read_segment(videos_root, segment_id)
    if str(segment.get("judge_status") or "") not in {"keep", "manual_keep"}:
        raise SegmentStateConflict("片段未通过内容复核，不能允许发布")
    if (segment.get("action_state") or {}).get("status") in {"pending", "processing"}:
        raise SegmentStateConflict("成片仍在后台处理，不能允许发布")
    artifacts = _normalize_artifacts(root, segment)
    final_item = artifacts.get("final_output") or {}
    final_rel = str(final_item.get("rel_path") or "")
    if not segment.get("final_media_id") or not final_rel or not bool(final_item.get("exists")):
        raise SegmentStateConflict("最终成片不存在，请先生成最终成片")
    final_path = _artifact_path(root, final_rel)
    if payload is not None:
        if ((payload.get("expected_revision") != segment.get("revision") and segment.get("publish_approval") != "approved")
                or payload.get("final_media_id") != _media_id(root, final_path)):
            raise SegmentStateConflict("成片版本已改变，请重新预览后允许发布")
    try:
        queue_item = get_upload_item(str(final_path))
    except Exception as exc:
        raise SegmentStateConflict("无法读取上传队列，已停止允许发布") from exc
    if queue_item is None:
        raise SegmentStateConflict("最终成片尚未进入等待确认队列")
    already_approved = str(segment.get("publish_approval") or "") == "approved"
    queue_status = str(queue_item.get("status") or "")
    if queue_status == "staged":
        queue_item = activate_staged_upload(str(final_path))
        if queue_item is None:
            raise SegmentStateConflict("等待确认的上传队列项已消失")
        queue_status = str(queue_item.get("status") or "")
    elif queue_status in {
        "queued",
        "uploading",
        "uploaded",
        "publishing",
        "published",
    }:
        # The unique video_path row makes a repeated approval a no-op.
        pass
    else:
        raise SegmentStateConflict(
            f"最终成片当前处于 {queue_status or '未知'} 状态，不能允许发布"
        )

    def mutate(_root: Path, _source_path: Path, current: dict[str, Any]) -> dict[str, Any]:
        current["upload_status"] = queue_status
        current["publish_approved_at"] = current.get("publish_approved_at") or _now()
        current["publish_approval"] = "approved"
        current["failure"] = None
        return current

    updated = _mutate_segment(videos_root, segment_id, mutate)
    updated["publish_idempotent"] = already_approved
    return updated


def prepare_missed_segment(
    videos_root: str | Path,
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a durable manual-missed segment record before Windows slicing."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    start = _finite_seconds(payload.get("start_seconds", payload.get("start")))
    end = _finite_seconds(payload.get("end_seconds", payload.get("end")))
    if start is None or end is None:
        raise ValueError("start_seconds and end_seconds must be numeric")
    if end <= start:
        raise ValueError("end_seconds must be greater than start_seconds")
    reason = str(payload.get("reason") or "").strip()
    if reason not in MISSED_SEGMENT_REASONS:
        raise ValueError(
            "reason must be one of: " + ", ".join(sorted(MISSED_SEGMENT_REASONS))
        )
    note = str(payload.get("note") or payload.get("review_note") or "").strip()

    root = Path(videos_root).expanduser().resolve()
    source = resolve_task_id(root, task_id)
    tasks = build_task_inventory(root, room_id=source.parent.name)
    task = next((item for item in tasks if item.get("task_id") == task_id), None)
    if task is None:
        raise FileNotFoundError(f"Source recording not found: {task_id}")
    if str(task.get("status") or "") in {"pending", "processing", "running"}:
        raise SegmentStateConflict("录播切片任务正在运行，暂不能补标")

    history_path = source.with_suffix(".mp4.task.json")
    with lock_task_history(source):
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            history = {
                "source_rel_path": source.relative_to(root).as_posix(),
                "status": "done",
            }
        segments = history.get("segments")
        if not isinstance(segments, list):
            segments = []
        segment_id = uuid.uuid4().hex
        candidate_name = (
            f"{format_seconds_for_filename(start)}s_{source.stem}"
            f"_manual_{segment_id}.mp4"
        )
        candidate = source.with_name(candidate_name)
        segment = {
            "segment_id": segment_id,
            "source_rel_path": source.relative_to(root).as_posix(),
            "candidate_path": str(candidate),
            "candidate_rel_path": candidate.relative_to(root).as_posix(),
            "start_seconds": start,
            "end_seconds": end,
            "candidate_start_seconds": start,
            "candidate_end_seconds": end,
            "judge_status": "manual_keep",
            "judge_error": "",
            "quality_reason": MISSED_SEGMENT_REASONS[reason],
            "missed_reason": reason,
            "review_note": note,
            "manual_origin": "missed_segment",
            "manual_override": True,
            "preview_available": False,
            "preview_reason": "等待 Windows worker 生成人工候选",
            "upload_status": "not_queued",
            "action_state": {
                "action": "create_missed_segment",
                "status": "pending",
                "job_id": "",
                "updated_at": _now(),
            },
        }
        segments.append(segment)
        history["segments"] = segments
        history["source_rel_path"] = source.relative_to(root).as_posix()
        _write_history(history_path, history)

    set_review_state(
        root,
        task_id,
        "source_review",
        source_rel_path=source.relative_to(root).as_posix(),
        room_id=source.parent.name,
    )
    return _normalize_segments(root, source, [segment])[0]


def create_missed_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a manual missed interval into a reviewable candidate on Windows."""
    root, source, segment = _read_segment(videos_root, segment_id)
    candidate = _segment_candidate_path(root, segment)
    start = _float(segment.get("start_seconds"))
    end = _float(segment.get("end_seconds"))
    if end <= start:
        raise ValueError("manual candidate range is invalid")
    if not _nonempty_file(candidate):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        temporary = candidate.with_name(
            f"{candidate.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp{candidate.suffix}"
        )
        try:
            slice_video(source, temporary, start, end - start)
            if not _nonempty_file(temporary):
                raise RuntimeError("manual candidate renderer produced no media")
            os.replace(temporary, candidate)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def mutate(_root: Path, _source: Path, current: dict[str, Any]) -> dict[str, Any]:
        current["candidate_path"] = str(candidate)
        current["candidate_rel_path"] = candidate.relative_to(_root).as_posix()
        current["candidate_media_id"] = _media_id(_root, candidate)
        current["preview_available"] = True
        current["preview_reason"] = ""
        current["judge_status"] = "manual_keep"
        current["upload_status"] = "not_queued"
        current["failure"] = None
        current["action_state"] = _next_action_state(
            current,
            "done",
            action="create_missed_segment",
        )
        return current

    return _mutate_segment(videos_root, segment_id, mutate)


def prepare_source_review_completion(
    videos_root: str | Path,
    task_id: str,
    *,
    confirmed_no_content: bool = False,
) -> dict[str, Any]:
    """Validate and close one recording's human review.

    A recording can close only after every candidate has a terminal human
    decision and every kept candidate has gone through final generation and
    the separate publish approval.  An empty result requires an explicit
    whole-recording confirmation from the user.
    """
    root = Path(videos_root).expanduser().resolve()
    source = resolve_task_id(root, task_id)
    tasks = build_task_inventory(root, room_id=source.parent.name)
    task = next((item for item in tasks if item.get("task_id") == task_id), None)
    if task is None:
        raise FileNotFoundError(f"Source recording not found: {task_id}")
    history = read_task_history(source) or {}
    lifecycle_state = read_recording_state(root, task_id) or {}
    segments = _normalize_segments(root, source, history.get("segments") or [])
    if str(task.get("status") or "") in {"pending", "processing", "running"}:
        raise SegmentStateConflict("录播切片任务正在运行，不能完成整场复核")
    if str(history.get("status") or "") in {"pending", "processing"}:
        raise SegmentStateConflict("录播任务历史仍显示处理中，不能完成整场复核")
    if str(lifecycle_state.get("review_state") or "") == "processing":
        raise SegmentStateConflict("录播任务仍处于处理中，不能完成整场复核")
    if source.with_suffix(".mp4.pending").is_file() or source.with_suffix(
        ".mp4.processing"
    ).is_file():
        raise SegmentStateConflict("录播仍有活跃任务标记，不能完成整场复核")
    if not segments and not confirmed_no_content:
        raise SegmentStateConflict("零候选录播需要明确确认整场没有精彩片段")

    from src.server.action_jobs import find_active_segment_job

    for segment in segments:
        segment_id = str(segment.get("segment_id") or "")
        if segment_id and find_active_segment_job(root, segment_id) is not None:
            raise SegmentStateConflict("仍有片段任务正在运行，不能完成整场复核")
        action_state = segment.get("action_state")
        if isinstance(action_state, dict) and str(action_state.get("status") or "") in {
            "pending",
            "processing",
        }:
            raise SegmentStateConflict("仍有片段任务未完成，不能完成整场复核")
        status = str(segment.get("judge_status") or "review")
        if status in UNRESOLVED_STATUSES or status not in {
            "keep",
            "manual_keep",
            "drop",
        }:
            raise SegmentStateConflict("仍有候选片段未完成内容复核")
        if status == "drop":
            continue
        if str(segment.get("publish_approval") or "") != "approved":
            raise SegmentStateConflict("仍有成片未完成第二次发布确认")
        if str(segment.get("upload_status") or "") not in {
            "queued",
            "uploaded",
            "uploading",
            "publishing",
            "published",
        }:
            raise SegmentStateConflict("已保留片段尚未进入可发布状态")
        final_item = (segment.get("artifacts") or {}).get("final_output")
        if not isinstance(final_item, dict) or not bool(final_item.get("exists")):
            raise SegmentStateConflict("已保留片段缺少最终成片")

    source_rel_path = source.relative_to(root).as_posix()
    completion = {
        "confirmed_no_content": bool(not segments and confirmed_no_content),
        "segment_count": len(segments),
        "kept_count": sum(
            str(item.get("judge_status") or "") in {"keep", "manual_keep"}
            for item in segments
        ),
        "dropped_count": sum(
            str(item.get("judge_status") or "") == "drop" for item in segments
        ),
    }
    state = set_review_state(
        root,
        task_id,
        "review_complete",
        source_rel_path=source_rel_path,
        room_id=source.parent.name,
        recorded_at=str(task.get("recorded_at") or ""),
        completion=completion,
    )
    experiences = record_review_experiences(
        root,
        room_id=source.parent.name,
        task_id=task_id,
        source_rel_path=source_rel_path,
        segments=segments,
    )
    return {
        "task_id": task_id,
        "source_rel_path": source_rel_path,
        "review_state": "review_complete",
        "state": state,
        "segments": segments,
        "experiences": experiences,
    }


@_review_write
def drop_segment(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a candidate as dropped without deleting the retained review file."""
    data = payload or {}

    def mutate(root: Path, _source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        if "expected_revision" in data and data["expected_revision"] != int(segment.get("revision") or 0):
            raise SegmentStateConflict("片段已改变，未执行丢弃")
        _ensure_unpublished(root, segment)
        candidate = (
            _segment_candidate_path(root, segment)
            if _candidate_rel_path(root, segment)
            or str(segment.get("candidate_path") or "")
            else None
        )
        item: dict[str, Any] | None
        if candidate is None:
            item = None
        else:
            try:
                item = get_upload_item(str(candidate))
            except Exception as exc:
                recorded_upload_state = str(
                    segment.get("upload_status") or "not_queued"
                )
                if recorded_upload_state not in {"", "not_queued", "skipped"}:
                    raise SegmentStateConflict(
                        "无法确认片段上传状态，已停止丢弃操作"
                    ) from exc
                item = None
        if item is not None:
            upload_state = str(item.get("status") or "queued")
            if upload_state in {"uploading", "uploaded", "publishing", "published"}:
                raise SegmentStateConflict(
                    f"片段已处于 {upload_state} 状态，不能直接丢弃"
                )
            if upload_state in {"staged", "queued", "failed"}:
                if not withdraw_staged_upload(str(candidate)):
                    raise SegmentStateConflict("无法安全撤销片段的上传队列项")
                delete_slice_upload_metadata(candidate)
        previous_status = str(segment.get("judge_status") or "")
        segment["judge_status"] = "drop"
        segment["upload_status"] = "not_queued"
        segment["manual_override"] = True
        if previous_status == "judge_failed" or isinstance(segment.get("failure"), dict):
            segment["_technical_failure"] = True
        reason = str(data.get("reason") or "").strip()
        if reason:
            segment["quality_reason"] = reason
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


@_review_write
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
        _invalidate_final_output(_root, segment)
        segment["start_seconds"] = start
        segment["end_seconds"] = end
        segment["manual_override"] = True
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


@_review_write
def retry_segment_judge(videos_root: str | Path, segment_id: str) -> dict[str, Any]:
    """Run LLM judging again for a retained candidate clip."""

    def mutate(root: Path, source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        _ensure_unpublished(root, segment)
        candidate = _segment_candidate_path(root, segment)
        if not candidate.is_file():
            raise FileNotFoundError(f"Candidate not found: {candidate}")
        start = _float(segment.get("start_seconds"))
        end = _float(segment.get("end_seconds"))
        danmaku_text = extract_danmaku_text(str(source.with_suffix(".xml")), start, end)
        analyze_kwargs: dict[str, Any] = {"danmaku_text": danmaku_text}
        guidance = profile_context_for_mimo(root, source.parent.name)
        if guidance:
            analyze_kwargs["guidance"] = guidance
        result = analyze_candidate(str(candidate), source.parent.name, **analyze_kwargs)
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
        segment.pop("failure", None)
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def render_segment(videos_root: str | Path, segment_id: str) -> dict[str, Any]:
    """Regenerate a final through the same artifact and human approval contract."""
    return finalize_segment(videos_root, segment_id)


@_review_write
def update_segment_subtitle_style(
    videos_root: str | Path,
    segment_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist per-slice burned-subtitle appearance on a segment.

    This only records the desired style; re-burning the candidate is a
    Windows-only ffmpeg action queued separately via ``reburn_subtitles``.
    """
    from src.burn.subtitle_burn import SubtitleStyle

    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    style = SubtitleStyle.from_mapping(payload)

    def mutate(_root: Path, _source: Path, segment: dict[str, Any]) -> dict[str, Any]:
        _invalidate_final_output(_root, segment)
        segment["subtitle_style"] = style.to_mapping()
        segment["_subtitle_style_source"] = "clip"
        segment["manual_override"] = True
        return segment

    return _mutate_segment(videos_root, segment_id, mutate)


def reburn_segment_subtitles(videos_root: str | Path, segment_id: str) -> dict[str, Any]:
    """Regenerate an unapproved final through the canonical publish gate."""
    return finalize_segment(videos_root, segment_id)


def _artifact_plan(
    root: Path,
    source: Path,
    segment: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    start = _float(segment.get("start_seconds"))
    end = _float(segment.get("end_seconds"))
    segment_key = hashlib.sha256(
        str(segment.get("segment_id") or "").encode("utf-8")
    ).hexdigest()[:12]
    range_key = hashlib.sha256(
        f"{source.relative_to(root).as_posix()}:{start:.3f}:{end:.3f}".encode("utf-8")
    ).hexdigest()[:10]
    style_payload = (
        segment.get("subtitle_style")
        if isinstance(segment.get("subtitle_style"), dict)
        else {}
    )
    style_key = hashlib.sha256(
        json.dumps(
            style_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:8]
    artifact_dir = source.parent / ".bilive-artifacts"
    artifact_stem = f"{segment_key}-{range_key}-source-time-v2"
    raw = artifact_dir / f"{artifact_stem}.raw.mp4"
    analysis = artifact_dir / f"{artifact_stem}.analysis.json"
    final = source.with_name(
        f"{format_seconds_for_filename(start)}s_{source.stem}"
        f"_final_{segment_key}_{range_key}_{style_key}_source-time-v2.mp4"
    )
    return {
        "raw_candidate": {"rel_path": raw.relative_to(root).as_posix()},
        "analysis_sidecar": {"rel_path": analysis.relative_to(root).as_posix()},
        "final_output": {"rel_path": final.relative_to(root).as_posix()},
    }


def _artifact_snapshot(
    root: Path,
    plan: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for name in ("raw_candidate", "analysis_sidecar", "final_output"):
        item = dict(plan.get(name) or {})
        rel_path = str(item.get("rel_path") or "")
        path = _artifact_path(root, rel_path) if rel_path else None
        item["exists"] = bool(path and path.is_file())
        if name == "final_output" and path is not None and path.is_file():
            item["media_id"] = _media_id(root, path)
        else:
            item.pop("media_id", None)
        snapshot[name] = item
    return snapshot


def _artifact_path(root: Path, rel_path: str) -> Path:
    path = (root / str(rel_path)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("Artifact path is outside Videos root") from None
    return path


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _load_reusable_finalize_analysis(
    root: Path,
    segment: dict[str, Any],
    canonical_path: Path,
    *,
    start: float,
    end: float,
) -> AnalysisResult | None:
    candidates = [canonical_path]
    analysis_path = str(segment.get("analysis_path") or "")
    if analysis_path:
        candidates.append(Path(analysis_path).expanduser())
    if _candidate_rel_path(root, segment) or str(segment.get("candidate_path") or ""):
        candidate_path = _segment_candidate_path(root, segment)
        candidates.append(
            candidate_path.with_name(f"{candidate_path.stem}_analysis.json")
        )

    seen: set[str] = set()
    canonical_resolved = canonical_path.resolve()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        key = str(resolved)
        if key in seen or not resolved.is_file():
            continue
        seen.add(key)
        analysis = _load_analysis_path(resolved)
        if analysis is None or not _valid_analysis_segments(analysis):
            continue
        if resolved == canonical_resolved or _analysis_matches_range(
            analysis, segment, start=start, end=end
        ):
            analysis.suggested_trim = None
            return analysis
    return None


def _load_analysis_path(path: Path) -> AnalysisResult | None:
    try:
        return AnalysisResult.from_json(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _valid_analysis_segments(analysis: AnalysisResult) -> bool:
    return bool(
        str(analysis.transcript or "").strip()
        and any(
            str(item.text or "").strip() and float(item.end) > float(item.start)
            for item in analysis.transcript_segments
        )
    )


def _analysis_matches_range(
    analysis: AnalysisResult,
    segment: dict[str, Any],
    *,
    start: float,
    end: float,
) -> bool:
    if (
        analysis.source_start is not None
        and analysis.source_end is not None
        and abs(float(analysis.source_start) - start) <= 0.01
        and abs(float(analysis.source_end) - end) <= 0.01
    ):
        return True
    trim = analysis.suggested_trim
    if trim is None:
        return False
    candidate_start = _float(
        analysis.candidate_start
        if analysis.candidate_start is not None
        else segment.get("candidate_start_seconds")
    )
    return (
        abs(candidate_start + float(trim.trim_start) - start) <= 0.01
        and abs(candidate_start + float(trim.trim_end) - end) <= 0.01
    )


def _analysis_from_audio(
    segment: dict[str, Any],
    audio: dict[str, Any],
    *,
    start: float,
    end: float,
) -> AnalysisResult:
    if not isinstance(audio, dict):
        raise RuntimeError("ASR returned an invalid response")
    transcript = str(audio.get("transcript") or "").strip()
    if not transcript:
        raise RuntimeError(str(audio.get("error") or "ASR produced no transcript"))
    transcript_segments: list[TranscriptSegment] = []
    raw_segments = audio.get("segments")
    if isinstance(raw_segments, list):
        for raw in raw_segments:
            if isinstance(raw, TranscriptSegment):
                item = raw
            elif isinstance(raw, dict):
                try:
                    item = TranscriptSegment(
                        start=max(0.0, float(raw.get("start", 0.0))),
                        end=float(raw.get("end", 0.0)),
                        text=str(raw.get("text") or "").strip(),
                    )
                except (TypeError, ValueError):
                    continue
            else:
                continue
            if item.text and item.end > item.start:
                transcript_segments.append(item)
    if not transcript_segments:
        raise RuntimeError("ASR produced no valid timestamped transcript segments")
    analysis = AnalysisResult(
        title=str(segment.get("title") or "直播切片"),
        description=str(segment.get("description") or ""),
        tags=_segment_tags(segment),
        quality_score=_float(segment.get("quality_score")),
        retain_recommendation=True,
        quality_reason=str(segment.get("quality_reason") or ""),
        judge_status="manual_keep",
        transcript=transcript,
        transcript_segments=transcript_segments,
        source_start=start,
        source_end=end,
    )
    _apply_segment_metadata_to_analysis(analysis, segment, start=start, end=end)
    return analysis


def _apply_segment_metadata_to_analysis(
    analysis: AnalysisResult,
    segment: dict[str, Any],
    *,
    start: float,
    end: float,
) -> None:
    analysis.title = str(segment.get("title") or analysis.title or "直播切片")
    analysis.description = str(segment.get("description") or "")
    analysis.tags = _segment_tags(segment)
    analysis.retain_recommendation = True
    analysis.judge_status = "manual_keep"
    analysis.judge_error = ""
    analysis.suggested_trim = None
    analysis.source_start = start
    analysis.source_end = end


def _write_analysis_atomic(path: Path, analysis: AnalysisResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.{os.getpid()}.tmp{path.suffix}")
    temporary.unlink(missing_ok=True)
    if not analysis.to_json_file(str(temporary)):
        raise OSError(f"failed to write analysis sidecar: {path}")
    os.replace(temporary, path)


def _queue_final_output(final_path: Path) -> dict[str, Any]:
    if os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1":
        return {"status": "skipped", "created": False}
    try:
        inserted = bool(insert_upload_queue(str(final_path)))
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if inserted:
        return {"status": "queued", "created": True}
    try:
        existing = get_upload_item(str(final_path))
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if existing is not None:
        status = (
            str(existing.get("status") or "queued")
            if isinstance(existing, dict)
            else "queued"
        )
        if status == "failed":
            retried = requeue_failed_upload(str(final_path))
            status = str((retried or {}).get("status") or "failed")
            if status == "failed":
                raise RuntimeError("failed upload row could not be requeued")
        return {"status": status, "created": False}
    raise RuntimeError("upload queue insert returned false")


def _read_segment(
    videos_root: str | Path,
    segment_id: str,
) -> tuple[Path, Path, dict[str, Any]]:
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
        for raw in segments:
            if isinstance(raw, dict) and raw.get("segment_id") == segment_id:
                return root, source, _normalize_segments(root, source, [raw])[0]
    raise FileNotFoundError(f"Segment not found: {segment_id}")


def _fail_finalize(
    videos_root: str | Path,
    segment_id: str,
    *,
    stage: str,
    code: str,
    summary: str,
    recovery_action: str,
    exc: Exception,
    plan: dict[str, dict[str, Any]],
    timings: dict[str, int],
) -> None:
    failure = {
        "stage": stage,
        "code": code,
        "summary": summary,
        "technical_details": f"{type(exc).__name__}: {exc}",
        "recovery_action": recovery_action,
    }

    def fail(
        root: Path,
        _source: Path,
        segment: dict[str, Any],
    ) -> dict[str, Any]:
        segment["judge_status"] = "judge_failed"
        segment["judge_error"] = summary
        segment["upload_status"] = "not_queued"
        segment["failure"] = failure
        segment["artifacts"] = _artifact_snapshot(root, plan)
        segment["timings_ms"] = dict(timings)
        segment["action_state"] = _next_action_state(segment, "failed")
        return segment

    _mutate_segment(videos_root, segment_id, fail)
    raise SegmentFinalizeError(failure)


def _next_action_state(
    segment: dict[str, Any],
    status: str,
    *,
    action: str | None = None,
) -> dict[str, Any]:
    state = (
        dict(segment.get("action_state"))
        if isinstance(segment.get("action_state"), dict)
        else {}
    )
    state.update(
        {
            "action": str(action or state.get("action") or "finalize_segment"),
            "status": status,
            "updated_at": _now(),
        }
    )
    return state


def _finish_timing(
    timings: dict[str, int],
    stage: str,
    stage_started: float,
    total_started: float,
) -> dict[str, int]:
    timings[stage] = _elapsed_ms(stage_started)
    timings["total"] = _elapsed_ms(total_started)
    return dict(timings)


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _load_segment_analysis(candidate: Path):
    from src.autoslice.analysis_result import AnalysisResult

    sidecar = candidate.with_name(f"{candidate.stem}_analysis.json")
    if not sidecar.is_file():
        return None
    try:
        return AnalysisResult.from_json(sidecar.read_text(encoding="utf-8"))
    except OSError:
        return None


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
        segment.setdefault("judge_status", "review")
        segment.setdefault("judge_error", "")
        segment.setdefault("upload_status", "not_queued")
        segment.setdefault("manual_override", False)
        preview_available = _preview_allowed(segment)
        segment["preview_available"] = preview_available
        segment["preview_reason"] = "" if preview_available else _preview_reason(segment)
        segment["candidate_media_id"] = _candidate_media_id(root, segment)
        final_rel = str((raw.get("artifacts") or {}).get("final_output", {}).get("rel_path") or "")
        upload_rel = final_rel or str(segment.get("candidate_rel_path") or "")
        if upload_rel and segment.get("upload_status") not in {"not_queued", "skipped", ""}:
            try:
                queued = get_upload_item(str(_artifact_path(root, upload_rel)))
            except Exception:
                segment["upload_state_available"] = False
            else:
                segment["upload_state_available"] = True
                if queued:
                    segment["upload_status"] = "awaiting_publish" if queued["status"] == "staged" else queued["status"]
        segment["revision"] = max(0, int(_float(segment.get("revision"))))
        for key in ("start_seconds", "end_seconds", "density_core_start", "density_core_end"):
            if key in segment:
                segment[key] = _float(segment.get(key))
        segment["quality"] = _normalize_quality(segment)
        segment["failure"] = _normalize_failure(segment)
        segment["artifacts"] = _normalize_artifacts(root, segment)
        final_rel = str((raw.get("artifacts") or {}).get("final_output", {}).get("rel_path") or "")
        segment["final_media_id"] = (
            _media_id(root, _artifact_path(root, final_rel))
            if final_rel and _nonempty_file(_artifact_path(root, final_rel)) else ""
        )
        timings = segment.get("timings_ms")
        segment["timings_ms"] = (
            {
                str(key): max(0, int(_float(value)))
                for key, value in timings.items()
            }
            if isinstance(timings, dict)
            else {}
        )
        state = segment.get("action_state")
        if isinstance(state, dict) and state.get("job_id") and state.get("status") in {"pending", "processing"}:
            from src.server.action_jobs import read_action_job
            try:
                job = read_action_job(root, str(state["job_id"]))
                state = {**state, "status": job.get("status", state.get("status"))}
                if job.get("failure"):
                    segment["failure"] = job["failure"]
            except (OSError, ValueError):
                state = {**state, "status": "blocked"}
                segment["failure"] = {"summary": "任务状态无法读取", "recovery_action": "核对原任务，勿重复提交"}
        segment["action_state"] = (
            {
                "action": str(state.get("action") or ""),
                "status": str(state.get("status") or "idle"),
                "job_id": str(state.get("job_id") or ""),
                "updated_at": str(state.get("updated_at") or ""),
            }
            if isinstance(state, dict)
            else {
                "action": "",
                "status": "idle",
                "job_id": "",
                "updated_at": "",
            }
        )
        normalized.append(segment)
    return normalized


def _normalize_quality(segment: dict[str, Any]) -> dict[str, Any]:
    current = (
        dict(segment.get("quality"))
        if isinstance(segment.get("quality"), dict)
        else {}
    )
    defaults = {
        "score": segment.get("quality_score"),
        "completeness_score": segment.get("completeness_score"),
        "confidence": segment.get("confidence"),
        "reason": str(segment.get("quality_reason") or ""),
        "topic_summary": str(segment.get("topic_summary") or ""),
    }
    for key, value in defaults.items():
        current.setdefault(key, value)
    return current


def _normalize_failure(segment: dict[str, Any]) -> dict[str, str] | None:
    current = segment.get("failure")
    if isinstance(current, dict) and current:
        return {
            "stage": str(current.get("stage") or "unknown"),
            "code": str(current.get("code") or "segment_failed"),
            "summary": str(current.get("summary") or "片段处理失败"),
            "technical_details": str(current.get("technical_details") or ""),
            "recovery_action": str(
                current.get("recovery_action") or "检查技术详情后重试"
            ),
        }
    judge_error = str(segment.get("judge_error") or "").strip()
    upload_error = str(segment.get("upload_error") or "").strip()
    if upload_error:
        return {
            "stage": "queue",
            "code": "upload_queue_failed",
            "summary": "片段未能加入上传队列",
            "technical_details": upload_error,
            "recovery_action": "检查上传数据库后重试",
        }
    if judge_error and str(segment.get("judge_status") or "") == "judge_failed":
        return {
            "stage": "judge",
            "code": "judge_failed",
            "summary": judge_error,
            "technical_details": judge_error,
            "recovery_action": "重新分析，或人工调整后生成成片",
        }
    return None


def _normalize_artifacts(
    root: Path,
    segment: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    current = (
        {
            str(key): dict(value)
            for key, value in segment.get("artifacts", {}).items()
            if isinstance(value, dict)
        }
        if isinstance(segment.get("artifacts"), dict)
        else {}
    )
    candidate_rel = _candidate_rel_path(root, segment)
    failure = segment.get("failure")
    retained_final_failure = (
        str(failure.get("stage") or "") in {"metadata", "queue"}
        if isinstance(failure, dict)
        else False
    )
    if not _preview_allowed(segment) and not retained_final_failure:
        current.pop("final_output", None)
    if "raw_candidate" not in current and candidate_rel and not _preview_allowed(segment):
        current["raw_candidate"] = {"rel_path": candidate_rel}
    if "final_output" not in current and candidate_rel and _preview_allowed(segment):
        current["final_output"] = {"rel_path": candidate_rel}
    if "analysis_sidecar" not in current and candidate_rel:
        candidate = (root / candidate_rel).resolve()
        legacy_analysis = candidate.with_name(f"{candidate.stem}_analysis.json")
        try:
            analysis_rel = legacy_analysis.relative_to(root).as_posix()
        except ValueError:
            analysis_rel = ""
        if analysis_rel:
            current["analysis_sidecar"] = {"rel_path": analysis_rel}

    normalized: dict[str, dict[str, Any]] = {}
    for name in ("raw_candidate", "analysis_sidecar", "final_output"):
        item = dict(current.get(name) or {})
        rel_path = str(item.get("rel_path") or "").replace("\\", "/")
        item["rel_path"] = rel_path
        path: Path | None = None
        if rel_path:
            try:
                path = _artifact_path(root, rel_path)
            except ValueError:
                path = None
        item["exists"] = bool(path and path.is_file())
        if (
            name == "final_output"
            and _preview_allowed(segment)
            and path is not None
            and path.is_file()
        ):
            item["media_id"] = _media_id(root, path)
        else:
            item.pop("media_id", None)
        normalized[name] = item
    return normalized


def _mutate_segment(
    videos_root: str | Path,
    segment_id: str,
    mutator,
    *,
    bump_revision: bool = True,
) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    for task in build_task_inventory(root):
        source = root / task["source_rel_path"]
        history_path = source.with_suffix(".mp4.task.json")
        if not history_path.is_file():
            continue
        with lock_task_history(source):
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
                previous_revision = max(0, int(_float(segment.get("revision"))))
                updated = mutator(root, source, segment)
                if bump_revision:
                    updated["revision"] = previous_revision + 1
                else:
                    updated["revision"] = previous_revision
                segments[index] = updated
                _write_history(history_path, history)
                set_review_state(
                    root,
                    str(task.get("task_id") or ""),
                    "candidate_review",
                    source_rel_path=source.relative_to(root).as_posix(),
                    room_id=source.parent.name,
                    recorded_at=str(task.get("recorded_at") or ""),
                )
                return _normalize_segments(root, source, [updated])[0]
    raise FileNotFoundError(f"Segment not found: {segment_id}")


def _write_history(path: Path, history: dict[str, Any]) -> None:
    tmp_path = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}."
        f"{uuid.uuid4().hex}.tmp"
    )
    tmp_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


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


def _apply_profile_metadata(
    root: Path,
    source: Path,
    segment: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Apply streamer defaults only when this clip has no explicit edit."""
    profile = read_streamer_profile(root, source.parent.name)
    if (
        "tags" not in payload
        and not segment.get("tags")
        and profile.get("default_tags")
    ):
        segment["tags"] = list(profile["default_tags"])
        segment["_metadata_source"] = "profile"
    if (
        "description" not in payload
        and not str(segment.get("description") or "").strip()
        and str(profile.get("default_description") or "").strip()
    ):
        segment["description"] = str(profile["default_description"])
        segment["_metadata_source"] = "profile"


def _apply_display_defaults(
    root: Path,
    source: Path,
    segments: list[dict[str, Any]],
) -> None:
    """Expose effective subtitle defaults without mutating task history."""
    from src.burn.subtitle_burn import SubtitleStyle
    from src.config import default_subtitle_style

    profile_style = profile_subtitle_style(root, source.parent.name)
    for segment in segments:
        source_name = str(segment.get("_subtitle_style_source") or "")
        if source_name == "clip" and isinstance(segment.get("subtitle_style"), dict):
            segment["subtitle_style"] = SubtitleStyle.from_mapping(
                segment["subtitle_style"]
            ).to_mapping()
        elif profile_style:
            segment["subtitle_style"] = SubtitleStyle.from_mapping(
                profile_style
            ).to_mapping()
            segment["_subtitle_style_source"] = "profile"
        else:
            segment["subtitle_style"] = default_subtitle_style().to_mapping()
            segment["_subtitle_style_source"] = "global"


def _segment_tags(segment: dict[str, Any]) -> list[str]:
    tags = segment.get("tags")
    if isinstance(tags, list):
        values = [str(item).strip() for item in tags if str(item).strip()]
    else:
        text = str(tags or "").strip()
        values = [text] if text else []
    return values or ["直播切片"]


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
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("Candidate path is outside Videos root") from None
        return candidate
    candidate = Path(str(segment.get("candidate_path") or "")).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Candidate path is outside Videos root") from None
    return candidate


def _summary_counts(segments: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in (*SUMMARY_KEYS, "awaiting_publish", "needs_repair")}
    for segment in segments:
        status = str(segment.get("judge_status") or "review")
        counts[status] = counts.get(status, 0) + 1
        if segment.get("upload_status") == "awaiting_publish":
            counts["awaiting_publish"] += 1
        if segment.get("failure") or segment.get("upload_status") == "failed":
            counts["needs_repair"] += 1
    return counts


def _candidate_rel_path(root: Path, segment: dict[str, Any]) -> str:
    rel = str(segment.get("candidate_rel_path") or "")
    if rel:
        try:
            return (root / rel).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return ""
    path_text = str(segment.get("candidate_path") or "")
    if not path_text:
        return ""
    try:
        return Path(path_text).resolve().relative_to(root).as_posix()
    except ValueError:
        return ""


def _candidate_media_id(root: Path, segment: dict[str, Any]) -> str:
    if not _preview_allowed(segment):
        return ""
    rel = _candidate_rel_path(root, segment)
    if not rel:
        return ""
    candidate = (root / rel).resolve()
    if not candidate.is_file():
        return ""
    return _media_id(root, candidate)


def _preview_allowed(segment: dict[str, Any]) -> bool:
    if str(segment.get("judge_status") or "") not in {"keep", "manual_keep"}:
        return False
    if "preview_available" in segment:
        return bool(segment.get("preview_available"))
    return True


def _preview_reason(segment: dict[str, Any]) -> str:
    if _preview_allowed(segment):
        return ""
    return str(
        segment.get("preview_reason")
        or segment.get("judge_error")
        or segment.get("quality_reason")
        or "内部候选未生成可审核短片"
    ).strip()


def _media_id(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root).as_posix()
    return base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _finite_seconds(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _recorded_at(source_name: str) -> str:
    match = re.search(
        r"(?P<date>\d{8})-(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})",
        Path(str(source_name)).name,
    )
    if not match:
        return ""
    date = match.group("date")
    return (
        f"{date[:4]}-{date[4:6]}-{date[6:8]} "
        f"{match.group('hour')}:{match.group('minute')}:{match.group('second')}"
    )
