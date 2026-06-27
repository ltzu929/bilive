# Copyright (c) 2024 bilive.
# Slice-only pipeline: skip full-stream rendering and generate/upload clips directly.

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path

from src.config import (
    MIN_VIDEO_SIZE,
    BURST_RATIO,
    BURST_WINDOW,
    BURST_CONTEXT,
    BURST_MERGE_GAP,
    BURST_TOP_N,
    MIMO_PARALLELISM,
)
from src.autoslice import slice_video_by_danmaku
from src.autoslice.candidate_analyzer import (
    analyze_candidate as _single_candidate_analyzer,
    analyze_candidate_clips as _multi_candidate_analyzer,
    unload_candidate_models,
)
from src.autoslice.danmaku_slice import extract_danmaku_text, format_seconds_for_filename
from src.burn.subtitle_burn import burn_subtitles_from_analysis
from src.burn.pipeline_stages import (
    analyze_clips_stage,
    enqueue_stage,
    metadata_stage,
    subtitle_stage,
)
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    write_slice_upload_metadata,
)
from src.upload.extract_video_info import get_video_info
from src.log.logger import scan_log
from src.burn.slice_progress import SliceProgressWriter
from src.db.conn import delete_upload_queue, get_upload_item, insert_upload_queue

analyze_candidate = _single_candidate_analyzer


def analyze_candidate_clips(*args, **kwargs):
    if analyze_candidate is not _single_candidate_analyzer:
        result = analyze_candidate(*args, **kwargs)
        return result if isinstance(result, list) else [result]
    return _multi_candidate_analyzer(*args, **kwargs)


def burn_subtitles_for_output(video_path, analysis, output_path):
    try:
        return burn_subtitles_from_analysis(
            video_path,
            analysis,
            output_path=output_path,
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


def _resolve_mimo_parallelism(value, total_slices):
    configured = MIMO_PARALLELISM if value is None else value
    try:
        workers = int(configured)
    except (TypeError, ValueError):
        workers = 1
    if total_slices <= 1:
        return 1
    return max(1, min(workers, total_slices))


def _format_score(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


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
    judge_failed_count = 0
    dropped_count = 0
    empty_candidate_count = 0
    mimo_results_by_index = {}
    mimo_parallelism = _resolve_mimo_parallelism(
        _slice_options.get("mimo_parallelism"),
        total_slices,
    )
    if mimo_parallelism > 1:
        scan_log.info(
            f"Submitting {total_slices} candidate(s) to MiMo with parallelism={mimo_parallelism}"
        )
        progress.update(
            force=True,
            status="running",
            phase="mimo_wait",
            phase_label="等待 MiMo 返回",
            current_slice=0,
            total_slices=total_slices,
            current_slice_percent=100.0,
            message=f"已并发发送 {total_slices} 个候选给 MiMo，并发数 {mimo_parallelism}",
            error="",
            diagnostics=diagnostics,
        )

        def run_mimo_candidate(index, generated_slice):
            danmaku_text = extract_danmaku_text(
                xml_path,
                generated_slice.context_start,
                generated_slice.context_end,
            )
            results = analyze_clips_stage(
                generated_slice.path,
                artist=artist,
                danmaku_text=danmaku_text,
                candidate_start=generated_slice.context_start,
                candidate_end=generated_slice.context_end,
                candidate_duration=generated_slice.duration,
                analyzer=analyze_candidate_clips,
            )
            return {
                "index": index,
                "danmaku_text": danmaku_text,
                "results": results,
            }

        with ThreadPoolExecutor(max_workers=mimo_parallelism) as executor:
            futures = {
                executor.submit(run_mimo_candidate, index, generated_slice): index
                for index, generated_slice in enumerate(slices_path, start=1)
            }
            completed = 0
            for future in as_completed(futures):
                index = futures[future]
                try:
                    mimo_results_by_index[index] = future.result()
                except Exception as exc:
                    mimo_results_by_index[index] = {"index": index, "error": exc}
                completed += 1
                diagnostics = upsert_diagnostic(
                    diagnostics,
                    diagnostic_item(
                        "mimo",
                        "MiMo 判断",
                        "pending" if completed < total_slices else "ok",
                        f"MiMo 并发判断完成 {completed}/{total_slices}",
                        [("并发数", str(mimo_parallelism)), ("已完成", f"{completed}/{total_slices}")],
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
                    message=f"MiMo 判断中：已完成 {completed}/{total_slices}，并发数 {mimo_parallelism}",
                    error="",
                    diagnostics=diagnostics,
                )
    for index, generated_slice in enumerate(slices_path, start=1):
        slice_path = generated_slice.path
        segment = None
        queue_created = False
        try:
            danmaku_text = extract_danmaku_text(
                xml_path,
                generated_slice.context_start,
                generated_slice.context_end,
            )
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
                ("弹幕数", str(int(getattr(generated_slice, "danmaku_count", 0) or 0))),
                ("弹幕字符", str(len(danmaku_text))),
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
            precomputed_mimo = mimo_results_by_index.get(index)
            if precomputed_mimo is not None:
                if precomputed_mimo.get("error") is not None:
                    raise precomputed_mimo["error"]
                danmaku_text = precomputed_mimo.get("danmaku_text", danmaku_text)
                results = precomputed_mimo["results"]
            else:
                results = analyze_clips_stage(
                    slice_path,
                    artist=artist,
                    danmaku_text=danmaku_text,
                    candidate_start=generated_slice.context_start,
                    candidate_end=generated_slice.context_end,
                    candidate_duration=generated_slice.duration,
                    analyzer=analyze_candidate_clips,
                )
            result_message = (
                f"MiMo 返回 {len(results)} 个可处理片段"
                if results
                else "MiMo 未返回可投稿片段"
            )
            diagnostics = upsert_diagnostic(
                diagnostics,
                diagnostic_item(
                    "mimo",
                    "MiMo 判断",
                    "ok" if results else "warning",
                    result_message,
                    [*mimo_details, ("返回片段", str(len(results)))],
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
                scan_log.info(f"MiMo found no postable chat clips in {slice_path}")
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
                )
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
                )

                if OMNI_ENABLE_DEEP_ANALYSIS:
                    analysis_json_path = output_path[:-4] + "_analysis.json"
                    result.to_json_file(analysis_json_path)
                    scan_log.info(f"Analysis result saved: {analysis_json_path}")

                burn_result = subtitle_stage(
                    slice_path,
                    result,
                    burner=lambda video, analysis, output_path=output_path: burn_subtitles_for_output(
                        video,
                        analysis,
                        output_path,
                    ),
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
                metadata_result = metadata_stage(
                    output_path,
                    result,
                    room_id=room_id,
                    writer=write_slice_upload_metadata,
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
                queue_result = enqueue_stage(
                    output_path,
                    insert=insert_upload_queue,
                    lookup=get_upload_item,
                    skip=os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1",
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
                segment["upload_status"] = queue_result["status"]
                if queue_result["status"] == "skipped":
                    scan_log.info(f"Skip upload queue for local test: {output_path}")
                elif queue_result["status"] == "queued":
                    scan_log.info(f"Slice ready for upload: {output_path}")
                else:
                    scan_log.info(
                        f"Slice already exists in upload queue "
                        f"({queue_result['status']}): {output_path}"
                    )

                if segment["upload_status"] == "skipped":
                    scan_log.info(f"Slice finalized without queueing: {output_path}")
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
                )
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

    if total_slices and not output_slices and not segments:
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
    elif os.getenv("BILIVE_DELETE_SOURCE_AFTER_SLICE") != "1":
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
    else:
        progress.update(
            force=True,
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="正在清理源文件",
            diagnostics=diagnostics,
        )
        for remove_path in [original_video_path, xml_path]:
            if os.path.exists(remove_path):
                os.remove(remove_path)
                scan_log.info(f"Removed: {remove_path}")
        set_diagnostic(
            diagnostic_item(
                "cleanup",
                "清理动作",
                "ok",
                "已清理源 mp4 和弹幕 XML",
                [("源文件", "已删除"), ("弹幕 XML", "已删除")],
            ),
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="源文件已清理",
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
    quality_reason = ""
    title = Path(slice_path).stem
    description = ""
    tags = []
    manual_override = False

    if analysis is not None:
        judge_status = analysis.judge_status or ("keep" if analysis.retain_recommendation else "drop")
        judge_error = analysis.judge_error
        quality_score = analysis.quality_score
        quality_reason = analysis.quality_reason
        title = analysis.title
        description = analysis.description
        tags = analysis.tags
        trim = analysis.suggested_trim
        if trim is not None:
            mimo_trim_start = float(trim.trim_start)
            mimo_trim_end = float(trim.trim_end)
        if trim is not None and judge_status == "keep":
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
        "quality_reason": quality_reason,
        "title": title,
        "description": description,
        "tags": tags,
        "upload_status": upload_status,
        "manual_override": manual_override,
    }


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
