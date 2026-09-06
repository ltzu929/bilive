# Copyright (c) 2024 bilive.
# Slice-only pipeline: skip full-stream rendering and generate/upload clips directly.

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import re
import time

from src.config import (
    MIN_VIDEO_SIZE,
    BURST_RATIO,
    BURST_WINDOW,
    BURST_CONTEXT,
    BURST_MERGE_GAP,
    BURST_TOP_N,
    BURST_LAG_SECONDS,
    DANMAKU_MAX_CHARS,
    DANMAKU_TIMELINE,
    MIMO_REQUEST_PARALLELISM,
)
from src.autoslice import slice_video_by_danmaku
from src.autoslice.candidate_analyzer import (
    analyze_candidate as _single_candidate_analyzer,
    analyze_candidate_clip_results as _candidate_clip_result_analyzer,
    analyze_candidate_clips as _multi_candidate_analyzer,
    judge_candidate_clips_only as _mimo_candidate_judge,
    route_below_quality_gate_to_review,
    unload_candidate_models,
)
from src.autoslice.danmaku_slice import extract_danmaku_text, format_seconds_for_filename
from src.burn.subtitle_burn import burn_subtitles_from_analysis
from src.burn.pipeline_stages import (
    analyze_clips_stage,
    metadata_stage,
    stage_upload_stage,
    subtitle_stage,
)
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    write_slice_features,
    write_slice_upload_metadata,
)
from src.upload.extract_video_info import get_video_info
from src.log.logger import scan_log
from src.burn.slice_progress import SliceProgressWriter
from src.db.conn import (
    delete_upload_queue,
    get_upload_item,
    insert_upload_queue,
    requeue_failed_upload,
    stage_upload_queue,
)

analyze_candidate = _single_candidate_analyzer


def analyze_candidate_clips(*args, **kwargs):
    if analyze_candidate is not _single_candidate_analyzer:
        result = analyze_candidate(*args, **kwargs)
        return result if isinstance(result, list) else [result]
    return _multi_candidate_analyzer(*args, **kwargs)


_DEFAULT_ANALYZE_CANDIDATE_CLIPS = analyze_candidate_clips
judge_candidate_clips_with_mimo = _mimo_candidate_judge


def analyze_candidate_clip_results(*args, **kwargs):
    return _candidate_clip_result_analyzer(*args, **kwargs)


def burn_subtitles_for_output(video_path, analysis, output_path, style=None):
    if style is None:
        from src.config import default_subtitle_style

        style = default_subtitle_style()
    try:
        return burn_subtitles_from_analysis(
            video_path,
            analysis,
            output_path=output_path,
            style=style,
        )
    except TypeError as exc:
        if "output_path" not in str(exc):
            raise
        return burn_subtitles_from_analysis(video_path, analysis)


def check_file_size(file_path):
    """Return file size in MB."""
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    return file_size_mb


def _format_seconds_range(start, end):
    if start is None or end is None:
        return "-"
    try:
        return f"{float(start):.3f}-{float(end):.3f}s"
    except (TypeError, ValueError):
        return "-"


def _relative_core_range(generated_slice):
    context_start = float(generated_slice.context_start or 0.0)
    duration = float(generated_slice.duration or 0.0)
    start = max(
        0.0,
        float(generated_slice.density_core_start or context_start) - context_start,
    )
    end = max(
        start,
        float(generated_slice.density_core_end or context_start) - context_start,
    )
    if duration > 0:
        start = min(duration, start)
        end = min(duration, end)
        end = max(start, end)
    return start, end


def _resolve_mimo_parallelism(value, total_slices):
    configured = MIMO_REQUEST_PARALLELISM if value is None else value
    try:
        workers = int(configured)
    except (TypeError, ValueError):
        workers = 1
    if total_slices <= 1:
        return 1
    return max(1, min(workers, total_slices))


def _ordered_pipeline_results(output_slices, segments):
    """Return stable source-time ordering after completion-order processing."""
    ordered_segments = sorted(
        segments,
        key=lambda segment: (
            float(segment.get("candidate_start_seconds") or 0.0),
            float(segment.get("start_seconds") or 0.0),
            str(segment.get("candidate_path") or ""),
        ),
    )
    dedupe_ids = {
        str(segment.get("_dedupe_key")): str(segment.get("segment_id"))
        for segment in ordered_segments
        if segment.get("_dedupe_key")
    }
    for segment in ordered_segments:
        duplicate_of = str(segment.get("duplicate_of") or "")
        if duplicate_of in dedupe_ids:
            segment["duplicate_of"] = dedupe_ids[duplicate_of]
        segment.pop("_dedupe_key", None)
    successful = set(output_slices)
    ordered_outputs = [
        str(segment.get("candidate_path"))
        for segment in ordered_segments
        if str(segment.get("candidate_path") or "") in successful
    ]
    seen = set(ordered_outputs)
    ordered_outputs.extend(sorted(path for path in output_slices if path not in seen))
    return ordered_outputs, ordered_segments


def _candidate_overlap_components(slices):
    """Group candidate indices whose context windows can contain duplicates."""
    components: list[set[int]] = []
    for index, candidate in enumerate(slices, start=1):
        start = float(candidate.context_start)
        end = float(candidate.context_end)
        matching = []
        for component_index, component in enumerate(components):
            if any(
                min(end, float(slices[member - 1].context_end))
                > max(start, float(slices[member - 1].context_start))
                for member in component
            ):
                matching.append(component_index)
        merged = {index}
        for component_index in reversed(matching):
            merged.update(components.pop(component_index))
        components.append(merged)
    return {
        member: component_id
        for component_id, component in enumerate(components)
        for member in component
    }


def _mark_cross_candidate_duplicates(items, source_path):
    """Route lower-scored overlapping, text-similar clips to manual review."""
    entries = []
    for index, candidate, precomputed in items:
        if precomputed.get("error") is not None:
            continue
        for result in precomputed.get("results") or []:
            if route_below_quality_gate_to_review(result):
                continue
            trim = getattr(result, "suggested_trim", None)
            if (
                result.judge_status != "keep"
                or not result.retain_recommendation
                or trim is None
            ):
                continue
            start = float(candidate.context_start) + float(trim.trim_start)
            end = float(candidate.context_start) + float(trim.trim_end)
            if end <= start:
                continue
            entries.append(
                {
                    "index": index,
                    "result": result,
                    "start": start,
                    "end": end,
                    "score": _quality_rank(result),
                    "text": str(result.topic_summary or result.title or ""),
                }
            )

    winners = []
    for entry in sorted(
        entries,
        key=lambda item: (
            -item["score"],
            item["start"],
            item["end"],
            item["index"],
        ),
    ):
        duplicate = next(
            (
                winner
                for winner in winners
                if _intervals_are_duplicate(entry, winner)
                and _text_similarity(entry["text"], winner["text"]) >= 0.50
            ),
            None,
        )
        if duplicate is None:
            entry["result"]._dedupe_key = segment_id_for(
                source_path,
                entry["start"],
                entry["end"],
            )
            winners.append(entry)
            continue
        result = entry["result"]
        duplicate_id = getattr(
            duplicate["result"],
            "_dedupe_key",
            segment_id_for(
                source_path,
                duplicate["start"],
                duplicate["end"],
            ),
        )
        reason = (
            "Duplicate clip routed to review: overlaps a higher-scored clip "
            f"({duplicate_id})"
        )
        result.judge_status = "review"
        result.retain_recommendation = False
        result.judge_error = reason
        result.quality_reason = (
            f"{result.quality_reason}; {reason}"
            if result.quality_reason
            else reason
        )
        result.duplicate_of = duplicate_id
        result.duplicate_reason = reason


def _quality_rank(result):
    def score(value):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    return (
        0.4 * score(result.quality_score)
        + 0.4 * score(result.completeness_score)
        + 0.2 * score(result.confidence)
    )


def _intervals_are_duplicate(left, right):
    overlap = max(
        0.0,
        min(left["end"], right["end"]) - max(left["start"], right["start"]),
    )
    if overlap <= 0:
        return False
    left_duration = left["end"] - left["start"]
    right_duration = right["end"] - right["start"]
    union = left_duration + right_duration - overlap
    iou = overlap / union if union > 0 else 0.0
    shorter_coverage = overlap / min(left_duration, right_duration)
    return iou >= 0.60 or shorter_coverage >= 0.80


def _text_similarity(left, right):
    def grams(value):
        normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", value.lower())
        if len(normalized) < 2:
            return {normalized} if normalized else set()
        return {normalized[index : index + 2] for index in range(len(normalized) - 1)}

    left_grams = grams(str(left or ""))
    right_grams = grams(str(right or ""))
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def _format_score(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _candidate_judgment_record(index, generated_slice, results, raw_source=None):
    clips = []
    raw_response = {}
    rejection_reasons = []
    for result in results or []:
        if hasattr(result, "to_dict"):
            clips.append(result.to_dict())
        raw = getattr(result, "raw_model_response", None)
        if not raw_response and isinstance(raw, dict):
            raw_response = dict(raw)
        status = str(getattr(result, "judge_status", "") or "")
        if status in {"review", "drop", "judge_failed"}:
            reason = getattr(result, "judge_error", "") or getattr(
                result, "quality_reason", ""
            )
            text = str(reason or "").strip()
            if text and text not in rejection_reasons:
                rejection_reasons.append(text)

    if not raw_response and isinstance(getattr(raw_source, "raw_response", None), dict):
        raw_response = dict(raw_source.raw_response)
    raw_clips = raw_response.get("clips") if isinstance(raw_response, dict) else None
    if isinstance(raw_clips, list):
        for clip in raw_clips:
            if not isinstance(clip, dict):
                continue
            if str(clip.get("decision") or "").strip().lower() != "drop":
                continue
            text = str(clip.get("reason") or "").strip()
            if text and text not in rejection_reasons:
                rejection_reasons.append(text)
    for reason in (
        getattr(raw_source, "empty_reason", ""),
        getattr(raw_source, "raw_response_summary", ""),
    ):
        text = str(reason or "").strip()
        if text and text not in rejection_reasons:
            rejection_reasons.append(text)

    decisions = [
        str(item.get("judge_status") or "")
        for item in clips
        if str(item.get("judge_status") or "")
    ]
    if decisions:
        decision = decisions[0] if len(set(decisions)) == 1 else "mixed"
    elif isinstance(raw_clips, list) and raw_clips and all(
        isinstance(clip, dict)
        and str(clip.get("decision") or "").strip().lower() == "drop"
        for clip in raw_clips
    ):
        decision = "drop"
    else:
        decision = "empty"
    return {
        "candidate_index": int(index),
        "candidate_path": str(generated_slice.path),
        "candidate_start_seconds": float(generated_slice.context_start),
        "candidate_end_seconds": float(generated_slice.context_end),
        "candidate_duration_seconds": float(generated_slice.duration),
        "decision": decision,
        "clips": clips,
        "raw_model_response": raw_response,
        "rejection_reasons": rejection_reasons,
    }


def _mimo_empty_result_details(results):
    details = []
    reason = str(getattr(results, "empty_reason", "") or "").strip()
    if reason:
        details.append(("Empty reason", reason))
    summary = str(getattr(results, "raw_response_summary", "") or "").strip()
    if summary and summary != reason:
        details.append(("MiMo response", summary))
    return details


def _mimo_empty_result_message(results):
    reason = str(getattr(results, "empty_reason", "") or "").strip()
    if not reason:
        reason = str(getattr(results, "raw_response_summary", "") or "").strip()
    if not reason:
        reason = "MiMo 未提供原因"
    return f"MiMo 未生成可投稿片段：{reason}"


def _mimo_empty_log_suffix(results):
    reason = str(getattr(results, "empty_reason", "") or "").strip()
    if reason:
        return f": reason={reason}"
    summary = str(getattr(results, "raw_response_summary", "") or "").strip()
    if summary:
        return f": response={summary}"
    return ""


def _log_mimo_clip_decision(clip_index, total_clips, result, output_path=None):
    trim = result.suggested_trim
    trim_range = (
        _format_seconds_range(trim.trim_start, trim.trim_end)
        if trim is not None
        else "-"
    )
    source_range = _format_seconds_range(result.source_start, result.source_end)
    output_text = f", output={output_path}" if output_path else ""
    title = result.title or "-"
    clip_type = result.clip_type or "-"
    status = result.judge_status or ("keep" if result.retain_recommendation else "drop")
    scan_log.info(
        f"Clip {clip_index}/{total_clips} {status}: title={title}, "
        f"type={clip_type}, score={_format_score(result.quality_score)}, "
        f"completeness={_format_score(result.completeness_score)}, "
        f"confidence={_format_score(result.confidence)}, source={source_range}, "
        f"trim={trim_range}{output_text}, reason={result.quality_reason or '-'}"
    )


def _log_slice_only_summary(
    total_slices,
    output_slices,
    judge_failed_count,
    dropped_count,
    empty_candidate_count,
    segments,
):
    scan_log.info(
        f"Slice-only summary: candidates={total_slices}, "
        f"final_clips={len(output_slices)}, judge_failed={judge_failed_count}, "
        f"dropped={dropped_count}, empty_candidates={empty_candidate_count}, "
        f"segments={len(segments)}"
    )


def slice_only(video_path, **_slice_options):
    """Run the standalone slice pipeline for one completed recording.

    Optional _slice_options override burst detection parameters:
        burst_ratio, burst_window, burst_context, burst_merge_gap, burst_top_n
    """
    if not os.path.exists(video_path):
        error = f"File {video_path} does not exist."
        scan_log.error(error)
        return {"status": "failed", "error": error}

    progress = SliceProgressWriter()
    diagnostics = []
    original_video_path = str(video_path)
    source_name = Path(original_video_path).name
    room_id = Path(original_video_path).parent.name
    xml_path = original_video_path[:-4] + ".xml"
    from src.dashboard.source_lifecycle import profile_context_for_mimo
    from src.dashboard.source_lifecycle import profile_subtitle_style
    from src.burn.subtitle_burn import SubtitleStyle
    from src.config import default_subtitle_style

    guidance = profile_context_for_mimo(
        Path(original_video_path).parent.parent,
        room_id,
    )
    configured_subtitle_style = profile_subtitle_style(
        Path(original_video_path).parent.parent,
        room_id,
    )
    automatic_subtitle_style = (
        SubtitleStyle.from_mapping(configured_subtitle_style)
        if configured_subtitle_style
        else default_subtitle_style()
    )

    def set_diagnostic(item, **progress_fields):
        nonlocal diagnostics
        diagnostics = upsert_diagnostic(diagnostics, item)
        return progress.update(
            force=True,
            diagnostics=diagnostics,
            **progress_fields,
        )

    if not os.path.exists(xml_path):
        scan_log.warning(f"No danmaku file for {video_path}, cannot slice by burst.")
        set_diagnostic(
            diagnostic_item(
                "input",
                "输入文件",
                "error",
                "缺少弹幕 XML，无法按弹幕切片",
                [("文件", source_name), ("弹幕 XML", "缺失")],
            ),
            status="error",
            phase="error",
            phase_label="错误",
            room_id=room_id,
            source_path=original_video_path,
            source_name=source_name,
            message="缺少弹幕 XML，无法按弹幕切片",
            error="缺少弹幕 XML",
        )
        return {
            "status": "failed",
            "error": "缺少弹幕 XML",
            "diagnostics": diagnostics,
        }

    file_size_mb = check_file_size(original_video_path)
    if file_size_mb < MIN_VIDEO_SIZE:
        scan_log.info(
            f"Video size too small ({file_size_mb}MB), "
            f"skip slicing: {original_video_path}"
        )
        diagnostics = upsert_diagnostic(
            diagnostics,
            diagnostic_item(
                "input",
                "输入文件",
                "ok",
                "录像和弹幕文件已就绪",
                [
                    ("文件", source_name),
                    ("大小", format_mb(file_size_mb)),
                    ("弹幕 XML", "存在"),
                ],
            ),
        )
        set_diagnostic(
            diagnostic_item(
                "result",
                "切片结果",
                "warning",
                "录像小于切片阈值，已跳过",
                [
                    ("大小", format_mb(file_size_mb)),
                    ("最小阈值", format_mb(MIN_VIDEO_SIZE)),
                ],
            ),
            status="complete",
            phase="complete",
            phase_label="完成",
            room_id=room_id,
            source_path=original_video_path,
            source_name=source_name,
            current_slice=0,
            total_slices=0,
            current_slice_percent=100.0,
            message="录像小于切片阈值，已跳过",
            error="",
        )
        return {
            "status": "skipped",
            "message": "录像小于切片阈值，已跳过",
            "slice_count": 0,
            "output_slices": [],
            "diagnostics": diagnostics,
        }

    diagnostics = upsert_diagnostic(
        diagnostics,
        diagnostic_item(
            "input",
            "输入文件",
            "ok",
            "录像和弹幕文件已就绪",
            [
                ("文件", source_name),
                ("大小", format_mb(file_size_mb)),
                ("弹幕 XML", "存在"),
            ],
        ),
    )
    diagnostics = upsert_diagnostic(
        diagnostics,
        diagnostic_item(
            "burst",
            "爆点检测",
            "running",
            "等待弹幕突增检测结果",
            [
                ("阈值", format_ratio(BURST_RATIO)),
                ("窗口", f"{BURST_WINDOW}s"),
                ("上下文", f"±{BURST_CONTEXT}s"),
            ],
        ),
    )

    scan_log.info(f"Starting slice-only processing: {original_video_path}")
    progress.update(
        force=True,
        status="running",
        phase="start",
        phase_label="准备切片",
        room_id=room_id,
        source_path=original_video_path,
        source_name=source_name,
        current_slice=0,
        total_slices=0,
        current_slice_path="",
        current_slice_percent=0.0,
        message="准备切片任务",
        error="",
        diagnostics=diagnostics,
    )

    progress.update(
        force=True,
        status="running",
        phase="info",
        phase_label="读取信息",
        message="读取录制信息",
    )
    title, artist, date = get_video_info(original_video_path)

    try:
        progress.update(
            force=True,
            status="running",
            phase="detect",
            phase_label="检测高能片段",
            message="正在检测弹幕突增片段",
        )

        def on_slice_progress(event):
            current_slice = event.get("current_slice", 0)
            total_slices = event.get("total_slices", 0)
            event_name = event.get("event", "slice_progress")
            if event_name == "detect_complete":
                set_diagnostic(
                    diagnostic_from_detection(event),
                    status="running",
                    phase="detect",
                    phase_label="检测高能片段",
                    room_id=room_id,
                    source_path=original_video_path,
                    source_name=source_name,
                    current_slice=0,
                    total_slices=0,
                    current_slice_path="",
                    current_slice_percent=0.0,
                    message=event.get("reason") or "弹幕突增检测完成",
                    error="",
                )
                return
            progress.update(
                force=event_name in {"slice_start", "slice_complete"},
                status="running",
                phase="slice",
                phase_label="切片中",
                room_id=room_id,
                source_path=original_video_path,
                source_name=source_name,
                current_slice=current_slice,
                total_slices=total_slices,
                current_slice_path=event.get("output_path", ""),
                current_slice_percent=event.get("percent", 0.0),
                message=f"正在切片 {current_slice}/{total_slices}",
                error="",
                diagnostics=diagnostics,
            )

        slices_path = slice_video_by_danmaku(
            xml_path,
            original_video_path,
            return_metadata=True,
            burst_ratio=_slice_options.get("burst_ratio", BURST_RATIO),
            burst_window=_slice_options.get("burst_window", BURST_WINDOW),
            burst_context=_slice_options.get("burst_context", BURST_CONTEXT),
            burst_merge_gap=_slice_options.get("burst_merge_gap", BURST_MERGE_GAP),
            burst_top_n=_slice_options.get("burst_top_n", BURST_TOP_N),
            burst_lag_seconds=_slice_options.get("burst_lag_seconds", BURST_LAG_SECONDS),
            progress_callback=on_slice_progress,
        )
        scan_log.info(f"Generated {len(slices_path)} slices")
    except Exception as e:
        scan_log.error(f"Error in slice_video_by_danmaku: {e}")
        progress.error(str(e))
        return {
            "status": "failed",
            "error": str(e),
            "diagnostics": diagnostics,
        }

    total_slices = len(slices_path)
    set_diagnostic(
        diagnostic_item(
            "result",
            "切片结果",
            "ok" if total_slices else "warning",
            f"生成 {total_slices} 个切片",
            [("切片数", str(total_slices))],
        ),
        status="running",
        phase="detect" if total_slices == 0 else "slice",
        phase_label="检测高能片段" if total_slices == 0 else "切片中",
        room_id=room_id,
        source_path=original_video_path,
        source_name=source_name,
        current_slice=0,
        total_slices=total_slices,
        current_slice_percent=0.0 if total_slices == 0 else 100.0,
        message=f"生成 {total_slices} 个切片",
        error="",
    )
    output_slices = []
    segments = []
    candidate_judgments = []
    judge_failed_count = 0
    dropped_count = 0
    empty_candidate_count = 0
    mimo_parallelism = _resolve_mimo_parallelism(
        _slice_options.get(
            "mimo_request_parallelism",
            _slice_options.get("mimo_parallelism"),
        ),
        total_slices,
    )
    danmaku_by_index = {
        index: extract_danmaku_text(
            xml_path,
            generated_slice.context_start,
            generated_slice.context_end,
            max_chars=DANMAKU_MAX_CHARS,
            with_timestamps=DANMAKU_TIMELINE,
            focus_start=generated_slice.density_core_start,
            focus_end=generated_slice.density_core_end,
            relative_to=generated_slice.context_start,
        )
        for index, generated_slice in enumerate(slices_path, start=1)
    }

    def run_mimo_candidate(index, generated_slice):
        started = time.perf_counter()
        core_start, core_end = _relative_core_range(generated_slice)
        results = analyze_clips_stage(
            generated_slice.path,
            artist=artist,
            danmaku_text=danmaku_by_index[index],
            candidate_start=generated_slice.context_start,
            candidate_end=generated_slice.context_end,
            candidate_duration=generated_slice.duration,
            candidate_core_start=core_start,
            candidate_core_end=core_end,
            single_clip=True,
            guidance=guidance,
            analyzer=judge_candidate_clips_with_mimo,
        )
        return {
            "index": index,
            "danmaku_text": danmaku_by_index[index],
            "results": results,
            "timings_ms": {
                "mimo": round((time.perf_counter() - started) * 1000, 1),
            },
        }

    def iter_candidate_work():
        nonlocal diagnostics
        if total_slices <= 1:
            for candidate_index, candidate in enumerate(slices_path, start=1):
                if (
                    analyze_candidate_clips is not _DEFAULT_ANALYZE_CANDIDATE_CLIPS
                    or analyze_candidate is not _single_candidate_analyzer
                ):
                    yield candidate_index, candidate, None
                else:
                    yield candidate_index, candidate, run_mimo_candidate(
                        candidate_index,
                        candidate,
                    )
            return

        component_by_index = _candidate_overlap_components(slices_path)
        component_sizes = {
            component_id: sum(
                1 for value in component_by_index.values() if value == component_id
            )
            for component_id in set(component_by_index.values())
        }
        component_results = {
            component_id: []
            for component_id in component_sizes
        }
        scan_log.info(
            f"Submitting {total_slices} candidate(s) to MiMo "
            f"with request_parallelism={mimo_parallelism}"
        )
        progress.update(
            force=True,
            status="running",
            phase="mimo_wait",
            phase_label="等待 MiMo 返回",
            current_slice=0,
            total_slices=total_slices,
            current_slice_percent=100.0,
            message=f"已并发发送 {total_slices} 个候选给 MiMo，请求并发数 {mimo_parallelism}",
            error="",
            diagnostics=diagnostics,
        )
        with ThreadPoolExecutor(max_workers=mimo_parallelism) as executor:
            futures = {
                executor.submit(run_mimo_candidate, index, generated_slice): index
                for index, generated_slice in enumerate(slices_path, start=1)
            }
            completed = 0
            for future in as_completed(futures):
                index = futures[future]
                try:
                    precomputed = future.result()
                except Exception as exc:
                    precomputed = {"index": index, "error": exc}
                completed += 1
                diagnostics = upsert_diagnostic(
                    diagnostics,
                    diagnostic_item(
                        "mimo",
                        "MiMo 判断",
                        "pending" if completed < total_slices else "ok",
                        f"MiMo 并发判断完成 {completed}/{total_slices}",
                        [
                            ("请求并发数", str(mimo_parallelism)),
                            ("已完成", f"{completed}/{total_slices}"),
                        ],
                    ),
                )
                progress.update(
                    force=True,
                    status="running",
                    phase="mimo_wait",
                    phase_label="等待 MiMo 返回",
                    current_slice=completed,
                    total_slices=total_slices,
                    current_slice_percent=100.0,
                    message=(
                        f"MiMo 判断中：已完成 {completed}/{total_slices}，"
                        f"请求并发数 {mimo_parallelism}"
                    ),
                    error="",
                    diagnostics=diagnostics,
                )
                component_id = component_by_index[index]
                component_results[component_id].append(
                    (index, slices_path[index - 1], precomputed)
                )
                if (
                    len(component_results[component_id])
                    < component_sizes[component_id]
                ):
                    continue
                ready_items = sorted(
                    component_results.pop(component_id),
                    key=lambda item: item[0],
                )
                _mark_cross_candidate_duplicates(
                    ready_items,
                    original_video_path,
                )
                # Only potentially-overlapping candidates wait for one another.
                # Independent ready groups can finalize while unrelated MiMo
                # requests continue in the pool.
                yield from ready_items

    for index, generated_slice, precomputed_mimo in iter_candidate_work():
        slice_path = generated_slice.path
        segment = None
        queue_created = False
        candidate_timings = dict(
            (precomputed_mimo or {}).get("timings_ms") or {}
        )
        try:
            danmaku_text = danmaku_by_index[index]
            core_abs_start = float(generated_slice.density_core_start or 0.0)
            core_abs_end = float(generated_slice.density_core_end or 0.0)
            mimo_details = [
                ("候选", f"{index}/{total_slices}"),
                (
                    "候选区间",
                    _format_seconds_range(
                        generated_slice.context_start,
                        generated_slice.context_end,
                    ),
                ),
                ("候选时长", f"{_format_score(generated_slice.duration)}s"),
                ("爆点核心", _format_seconds_range(core_abs_start, core_abs_end)),
                ("弹幕数", str(int(getattr(generated_slice, "danmaku_count", 0) or 0))),
                ("弹幕字符", str(len(danmaku_text))),
                ("判断方式", "MiMo 视频+弹幕"),
            ]
            diagnostics = upsert_diagnostic(
                diagnostics,
                diagnostic_item(
                    "mimo",
                    "MiMo 判断",
                    "pending",
                    f"等待 MiMo 返回候选 {index}/{total_slices}",
                    mimo_details,
                ),
            )
            progress.update(
                force=True,
                status="running",
                phase="mimo_wait",
                phase_label="等待 MiMo 返回",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                current_slice_percent=100.0,
                message=f"已发送候选 {index}/{total_slices} 给 MiMo，等待判断结果",
                error="",
                diagnostics=diagnostics,
            )
            empty_result_source = None
            if precomputed_mimo is not None:
                if precomputed_mimo.get("error") is not None:
                    raise precomputed_mimo["error"]
                danmaku_text = precomputed_mimo.get("danmaku_text", danmaku_text)
                empty_result_source = precomputed_mimo["results"]
                core_start, core_end = _relative_core_range(generated_slice)
                asr_started = time.perf_counter()
                results = analyze_candidate_clip_results(
                    precomputed_mimo["results"],
                    slice_path,
                    artist,
                    candidate_start=generated_slice.context_start,
                    candidate_end=generated_slice.context_end,
                    candidate_duration=generated_slice.duration,
                    candidate_core_start=core_start,
                    candidate_core_end=core_end,
                    post_judge_asr=True,
                )
                candidate_timings["asr"] = round(
                    (time.perf_counter() - asr_started) * 1000,
                    1,
                )
            else:
                analysis_started = time.perf_counter()
                results = analyze_clips_stage(
                    slice_path,
                    artist=artist,
                    danmaku_text=danmaku_text,
                    candidate_start=generated_slice.context_start,
                    candidate_end=generated_slice.context_end,
                    candidate_duration=generated_slice.duration,
                    guidance=guidance,
                    analyzer=analyze_candidate_clips,
                )
                candidate_timings["analysis"] = round(
                    (time.perf_counter() - analysis_started) * 1000,
                    1,
                )
                empty_result_source = results
            result_message = (
                f"MiMo 返回 {len(results)} 个可处理片段"
                if results
                else _mimo_empty_result_message(empty_result_source)
            )
            candidate_judgments.append(
                _candidate_judgment_record(
                    index,
                    generated_slice,
                    results,
                    empty_result_source,
                )
            )
            empty_details = [] if results else _mimo_empty_result_details(empty_result_source)
            diagnostics = upsert_diagnostic(
                diagnostics,
                diagnostic_item(
                    "mimo",
                    "MiMo 判断",
                    "ok" if results else "warning",
                    result_message,
                    [
                        *mimo_details,
                        ("返回片段", str(len(results))),
                        *empty_details,
                    ],
                ),
            )
            progress.update(
                force=True,
                status="running",
                phase="mimo_result",
                phase_label="解析 MiMo 结果",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                current_slice_percent=100.0,
                message=result_message,
                error="",
                diagnostics=diagnostics,
            )
            if not results:
                empty_candidate_count += 1
                scan_log.info(
                    f"MiMo found no postable chat clips in {slice_path}"
                    f"{_mimo_empty_log_suffix(empty_result_source)}"
                )
                continue
            context_range = _format_seconds_range(
                getattr(generated_slice, "context_start", None),
                getattr(generated_slice, "context_end", None),
            )
            scan_log.info(
                f"MiMo returned {len(results)} chat clip(s) for candidate {slice_path}: "
                f"context={context_range}, "
                f"duration={_format_score(getattr(generated_slice, 'duration', None))}s, "
                f"danmaku_count={int(getattr(generated_slice, 'danmaku_count', 0) or 0)}, "
                f"danmaku_chars={len(danmaku_text)}"
            )

            from src.config import OMNI_ENABLE_DEEP_ANALYSIS
            from src.config import (
                EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                EDIT_ENABLE_INSTRUCTION,
                EDIT_ENABLE_PROMPT_PACKAGE,
                EDIT_MAX_SUBTITLE_EVIDENCE,
            )
            from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs
            from src.autoslice.edit_instruction import TimeRange

            for clip_index, result in enumerate(results, start=1):
                segment = build_segment_record(
                    original_video_path,
                    generated_slice,
                    result,
                    upload_status="not_queued",
                    danmaku_text=danmaku_text,
                )
                segment["timings_ms"] = dict(candidate_timings)
                if result.judge_status in {"judge_failed", "review"}:
                    if result.judge_status == "judge_failed":
                        judge_failed_count += 1
                    _log_mimo_clip_decision(clip_index, len(results), result)
                    scan_log.warning(
                        f"Slice {slice_path} kept for manual review: "
                        f"{result.judge_error or result.quality_reason}"
                    )
                    segments.append(segment)
                    continue

                if result.judge_status == "drop" or not result.retain_recommendation:
                    dropped_count += 1
                    _log_mimo_clip_decision(clip_index, len(results), result)
                    scan_log.info(
                        f"Slice {slice_path} filtered by LLM judge: "
                        f"retain=False, reason={result.quality_reason}"
                    )
                    segment["judge_status"] = "drop"
                    segments.append(segment)
                    if len(results) == 1 and os.path.exists(slice_path):
                        os.remove(slice_path)
                    continue

                output_path = clip_output_path(slice_path, result, clip_index)
                _log_mimo_clip_decision(clip_index, len(results), result, output_path)
                segment = build_segment_record(
                    original_video_path,
                    generated_slice,
                    result,
                    upload_status="not_queued",
                    candidate_path_override=output_path,
                    danmaku_text=danmaku_text,
                )
                segment["artifacts"] = {
                    "final_output": {
                        "rel_path": Path(output_path)
                        .resolve()
                        .relative_to(Path(original_video_path).parent.parent.resolve())
                        .as_posix(),
                        "exists": False,
                    }
                }
                segment["subtitle_style"] = automatic_subtitle_style.to_mapping()
                segment["_subtitle_style_source"] = "profile" if configured_subtitle_style else "global"
                segment["timings_ms"] = dict(candidate_timings)

                if OMNI_ENABLE_DEEP_ANALYSIS:
                    analysis_json_path = output_path[:-4] + "_analysis.json"
                    result.to_json_file(analysis_json_path)
                    scan_log.info(f"Analysis result saved: {analysis_json_path}")

                subtitle_started = time.perf_counter()
                burn_result = subtitle_stage(
                    slice_path,
                    result,
                    burner=lambda video, analysis, output_path=output_path: burn_subtitles_for_output(
                        video,
                        analysis,
                        output_path,
                        style=automatic_subtitle_style,
                    ),
                )
                segment["timings_ms"]["subtitle"] = round(
                    (time.perf_counter() - subtitle_started) * 1000,
                    1,
                )
                if not burn_result["ok"]:
                    reason = burn_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    scan_log.warning(f"{reason}: {slice_path}")
                    segments.append(segment)
                    continue
                segment["artifacts"]["final_output"]["exists"] = True
                # ``build_segment_record`` runs before ffmpeg creates the
                # output, so its initial preview flag is false.  The burned
                # final artifact is the user-facing preview and must become
                # available before the staged publish approval.
                segment["preview_available"] = True
                segment["preview_reason"] = ""
                scan_log.info(f"ASR subtitles burned into slice: {output_path}")

                trim_duration = (
                    float(result.source_end) - float(result.source_start)
                    if result.source_start is not None and result.source_end is not None
                    else generated_slice.duration
                )
                maybe_write_edit_outputs(
                    analysis=result,
                    source_video=original_video_path,
                    slice_video=slice_path,
                    artist=artist,
                    slice_duration=trim_duration,
                    output_video=output_path,
                    enable_edit_instruction=EDIT_ENABLE_INSTRUCTION,
                    enable_prompt_package=EDIT_ENABLE_PROMPT_PACKAGE,
                    max_subtitle_evidence=EDIT_MAX_SUBTITLE_EVIDENCE,
                    default_highlight_window=EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                    density_core=TimeRange(
                        start=generated_slice.density_core_start,
                        end=generated_slice.density_core_end,
                    ),
                    context_window=TimeRange(
                        start=generated_slice.context_start,
                        end=generated_slice.context_end,
                    ),
                )

                progress.update(
                    force=True,
                    status="running",
                    phase="metadata",
                    phase_label="写入元数据",
                    current_slice=index,
                    total_slices=total_slices,
                    current_slice_path=output_path,
                    message="正在写入上传参数",
                    diagnostics=diagnostics,
                )
                metadata_started = time.perf_counter()
                metadata_result = metadata_stage(
                    output_path,
                    result,
                    room_id=room_id,
                    writer=write_slice_upload_metadata,
                    source_task_id=base64.urlsafe_b64encode(str(segment["source_rel_path"]).encode()).decode().rstrip("="),
                    segment_id=str(segment["segment_id"]),
                )
                segment["timings_ms"]["metadata"] = round(
                    (time.perf_counter() - metadata_started) * 1000,
                    1,
                )
                if not metadata_result["ok"]:
                    reason = metadata_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    delete_slice_upload_metadata(output_path)
                    segments.append(segment)
                    continue

                progress.update(
                    force=True,
                    status="running",
                    phase="queue",
                    phase_label="加入上传队列",
                    current_slice=index,
                    total_slices=total_slices,
                    current_slice_path=output_path,
                    message="正在加入上传队列",
                    diagnostics=diagnostics,
                )
                queue_started = time.perf_counter()
                queue_result = stage_upload_stage(
                    output_path,
                    stage=stage_upload_queue,
                    skip=os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1",
                )
                segment["timings_ms"]["queue"] = round(
                    (time.perf_counter() - queue_started) * 1000,
                    1,
                )
                if not queue_result["ok"]:
                    reason = queue_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    delete_slice_upload_metadata(output_path)
                    segments.append(segment)
                    scan_log.error(f"{reason}: {output_path}")
                    continue
                queue_created = bool(queue_result.get("created"))
                segment["upload_status"] = (
                    "awaiting_publish"
                    if queue_result["status"] == "staged"
                    else queue_result["status"]
                )
                if queue_result["status"] == "skipped":
                    scan_log.info(f"Skip upload queue for local test: {output_path}")
                elif queue_result["status"] == "staged":
                    scan_log.info(
                        f"Slice staged and waiting for publish approval: {output_path}"
                    )
                elif queue_result["status"] == "queued":
                    scan_log.info(f"Slice already approved for upload: {output_path}")
                else:
                    scan_log.info(
                        f"Slice already exists in upload queue "
                        f"({queue_result['status']}): {output_path}"
                    )

                if segment["upload_status"] == "skipped":
                    scan_log.info(f"Slice finalized without queueing: {output_path}")
                try:
                    write_slice_features(
                        output_path,
                        {
                            "title": segment.get("title"),
                            "quality_score": segment.get("quality_score"),
                            "completeness_score": getattr(
                                result, "completeness_score", None
                            ),
                            "confidence": getattr(result, "confidence", None),
                            "burst_ratio": _slice_options.get(
                                "burst_ratio", BURST_RATIO
                            ),
                            "burst_context": _slice_options.get(
                                "burst_context", BURST_CONTEXT
                            ),
                            "lag_seconds": _slice_options.get(
                                "burst_lag_seconds", BURST_LAG_SECONDS
                            ),
                            "danmaku_count": segment.get("danmaku_count"),
                            "trim_duration": trim_duration,
                            "context_start": segment.get("candidate_start_seconds"),
                            "context_end": segment.get("candidate_end_seconds"),
                        },
                    )
                except OSError as feature_error:
                    scan_log.warning(
                        f"Failed to write slice feature sidecar for "
                        f"{output_path}: {feature_error}"
                    )
                output_slices.append(output_path)
                segments.append(segment)

        except Exception as e:
            scan_log.error(f"Error processing slice {slice_path}: {e}")
            progress.error(str(e), current_slice=index, total_slices=total_slices)
            judge_failed_count += 1
            if segment is None:
                segment = build_segment_record(
                    original_video_path,
                    generated_slice,
                    None,
                    upload_status="not_queued",
                    danmaku_text=danmaku_text,
                )
                segment["timings_ms"] = dict(candidate_timings)
            segment["judge_status"] = "judge_failed"
            segment["judge_error"] = str(e)
            segment["quality_reason"] = str(e)
            cleanup_path = (
                segment.get("candidate_path", slice_path)
                if isinstance(segment, dict)
                else slice_path
            )
            if queue_created:
                delete_upload_queue(cleanup_path)
            segment["upload_status"] = "not_queued"
            segments.append(segment)
            delete_slice_upload_metadata(cleanup_path)

    output_slices, segments = _ordered_pipeline_results(output_slices, segments)

    if (
        total_slices
        and not output_slices
        and not segments
        and empty_candidate_count < total_slices
    ):
        _log_slice_only_summary(
            total_slices,
            output_slices,
            judge_failed_count,
            dropped_count,
            empty_candidate_count,
            segments,
        )
        error = "所有候选切片处理失败"
        progress.error(error, current_slice=total_slices, total_slices=total_slices)
        return {
            "status": "failed",
            "error": error,
            "candidate_judgments": candidate_judgments,
            "diagnostics": diagnostics,
        }

    if total_slices:
        scan_log.info("Unloading candidate analysis models after slice batch")
        unload_candidate_models()

    if total_slices == 0:
        scan_log.info("No slices generated; keep original video/danmaku files.")
        set_diagnostic(
            diagnostic_item(
                "cleanup",
                "清理动作",
                "ok",
                "0 切片，源文件已保留",
                [("源文件", "保留"), ("弹幕 XML", "保留")],
            ),
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="0 切片，源文件已保留",
        )
    else:
        scan_log.info("Keep original video/danmaku files after slicing.")
        set_diagnostic(
            diagnostic_item(
                "cleanup",
                "清理动作",
                "ok",
                "源文件已保留",
                [("源文件", "保留"), ("弹幕 XML", "保留")],
            ),
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="源文件已保留",
        )

    progress.complete(
        message="未生成切片，源文件已保留" if total_slices == 0 else "切片处理完成",
        room_id=room_id,
        source_path=original_video_path,
        source_name=source_name,
        current_slice=total_slices,
        total_slices=total_slices,
        diagnostics=diagnostics,
    )
    _log_slice_only_summary(
        total_slices,
        output_slices,
        judge_failed_count,
        dropped_count,
        empty_candidate_count,
        segments,
    )
    scan_log.info(f"Slice-only processing complete for: {original_video_path}")
    return {
        "status": "done",
        "slice_count": len(output_slices),
        "judge_failed_count": judge_failed_count,
        "output_slices": output_slices,
        "segments": segments,
        "candidate_judgments": candidate_judgments,
        "diagnostics": diagnostics,
    }


def diagnostic_item(item_id, title, status, message, details):
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "message": message,
        "details": [
            {"label": str(label), "value": str(value)}
            for label, value in details
        ],
    }


def upsert_diagnostic(items, item):
    return [
        *(existing for existing in items if existing.get("id") != item.get("id")),
        item,
    ]


def build_segment_record(
    source_path,
    generated_slice,
    analysis,
    upload_status="not_queued",
    candidate_path_override=None,
    danmaku_text="",
):
    slice_path = str(candidate_path_override or generated_slice.path)
    candidate_start = float(getattr(generated_slice, "context_start", 0.0) or 0.0)
    candidate_end = float(getattr(generated_slice, "context_end", 0.0) or 0.0)
    start = candidate_start
    end = candidate_end
    mimo_trim_start = None
    mimo_trim_end = None
    judge_status = "keep"
    judge_error = ""
    quality_score = None
    completeness_score = None
    confidence = None
    duplicate_of = ""
    duplicate_reason = ""
    dedupe_key = ""
    quality_reason = ""
    title = Path(slice_path).stem
    description = ""
    tags = []
    manual_override = False
    raw_model_response = {}
    rejection_reasons = []

    if analysis is not None:
        judge_status = analysis.judge_status or ("keep" if analysis.retain_recommendation else "drop")
        judge_error = analysis.judge_error
        quality_score = analysis.quality_score
        completeness_score = getattr(analysis, "completeness_score", None)
        confidence = getattr(analysis, "confidence", None)
        duplicate_of = str(getattr(analysis, "duplicate_of", "") or "")
        duplicate_reason = str(
            getattr(analysis, "duplicate_reason", "") or ""
        )
        dedupe_key = str(getattr(analysis, "_dedupe_key", "") or "")
        quality_reason = analysis.quality_reason
        title = analysis.title
        description = analysis.description
        tags = analysis.tags
        raw_model_response = dict(
            getattr(analysis, "raw_model_response", {}) or {}
        )
        if judge_status in {"review", "drop", "judge_failed"}:
            reason = analysis.judge_error or analysis.quality_reason
            text = str(reason or "").strip()
            if text:
                rejection_reasons.append(text)
        trim = analysis.suggested_trim
        if trim is not None:
            mimo_trim_start = float(trim.trim_start)
            mimo_trim_end = float(trim.trim_end)
        if trim is not None and judge_status in {"keep", "review"}:
            start = (
                float(analysis.source_start)
                if analysis.source_start is not None
                else candidate_start + mimo_trim_start
            )
            end = (
                float(analysis.source_end)
                if analysis.source_end is not None
                else candidate_start + mimo_trim_end
            )

    preview_available = bool(
        candidate_path_override
        and judge_status in {"keep", "manual_keep"}
        and os.path.isfile(slice_path)
    )
    return {
        "segment_id": segment_id_for(source_path, start, end),
        "source_rel_path": source_rel_path(source_path),
        "candidate_path": slice_path,
        "candidate_rel_path": str(Path(source_path).parent.name + "/" + Path(slice_path).name),
        "candidate_start_seconds": candidate_start,
        "candidate_end_seconds": candidate_end,
        "mimo_trim_start": mimo_trim_start,
        "mimo_trim_end": mimo_trim_end,
        "start_seconds": start,
        "end_seconds": end,
        "density_core_start": float(getattr(generated_slice, "density_core_start", candidate_start) or candidate_start),
        "density_core_end": float(getattr(generated_slice, "density_core_end", candidate_end) or candidate_end),
        "danmaku_count": int(getattr(generated_slice, "danmaku_count", 0) or 0),
        "judge_status": judge_status,
        "judge_error": judge_error,
        "quality_score": quality_score,
        "completeness_score": completeness_score,
        "confidence": confidence,
        "duplicate_of": duplicate_of,
        "duplicate_reason": duplicate_reason,
        "_dedupe_key": dedupe_key,
        "quality_reason": quality_reason,
        "mimo_raw_response": raw_model_response,
        "rejection_reasons": rejection_reasons,
        "transcript_summary": _bounded_summary(
            getattr(analysis, "transcript", "") if analysis is not None else ""
        ),
        "danmaku_summary": _bounded_summary(danmaku_text),
        "preview_available": preview_available,
        "preview_reason": "" if preview_available else (
            "; ".join(rejection_reasons)
            or "内部候选未生成可审核短片"
        ),
        "title": title,
        "description": description,
        "tags": tags,
        "upload_status": upload_status,
        "manual_override": manual_override,
    }


def _bounded_summary(value, limit=1000):
    return " ".join(str(value or "").split())[:limit]


def segment_id_for(source_path, start, end):
    raw = f"{source_rel_path(source_path)}:{float(start):.3f}:{float(end):.3f}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def source_rel_path(source_path):
    source = Path(source_path)
    return f"{source.parent.name}/{source.name}"


def clip_output_path(candidate_path, analysis, index):
    source_start = (
        analysis.source_start
        if analysis.source_start is not None
        else float(index)
    )
    stem = Path(candidate_path).stem
    suffix = Path(candidate_path).suffix
    return str(
        Path(candidate_path).with_name(
            f"{format_seconds_for_filename(source_start)}s_{stem}_clip{index}{suffix}"
        )
    )


def diagnostic_from_detection(event):
    selected = int(event.get("selected_bursts") or 0)
    status = "ok" if selected else "warning"
    message = event.get("reason") or (
        f"检测到 {selected} 个可切片爆点" if selected else "未检测到超过阈值的弹幕突增"
    )
    details = [
        ("弹幕数", str(int(event.get("danmaku_count") or 0))),
        ("时长", format_duration(event.get("duration_seconds") or 0)),
        ("阈值", format_ratio(event.get("burst_ratio") or BURST_RATIO)),
        ("窗口", f"{int(event.get('burst_window') or BURST_WINDOW)}s"),
        ("基线密度", f"{float(event.get('baseline_density') or 0):.2f}/s"),
        ("候选爆点", str(int(event.get("detected_segments") or 0))),
    ]
    max_ratio = event.get("max_burst_ratio")
    if max_ratio is not None:
        details.append(("最高突增", format_ratio(max_ratio)))
    return diagnostic_item("burst", "爆点检测", status, message, details)


def format_mb(value):
    return f"{float(value):.1f} MB"


def format_ratio(value):
    return f"{float(value):.1f}x"


def format_duration(seconds):
    seconds = float(seconds or 0)
    if seconds <= 0:
        return "-"
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    return f"{minutes}m{remainder:02d}s"
