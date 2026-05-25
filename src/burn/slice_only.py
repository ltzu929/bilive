# Copyright (c) 2024 bilive.
# Slice-only pipeline: skip full-stream rendering and generate/upload clips directly.

import os
from pathlib import Path

from src.config import (
    MIN_VIDEO_SIZE,
    BURST_RATIO,
    BURST_WINDOW,
    BURST_CONTEXT,
    BURST_MERGE_GAP,
    BURST_TOP_N,
)
from autoslice import slice_video_by_danmaku
from src.autoslice.danmaku_slice import extract_danmaku_text
from src.autoslice.title_generator import generate_title
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    write_slice_upload_metadata,
)
from src.upload.extract_video_info import get_video_info
from src.log.logger import scan_log
from src.burn.slice_progress import SliceProgressWriter
from db.conn import insert_upload_queue


def check_file_size(file_path):
    """Return file size in MB."""
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    return file_size_mb


def unload_local_audio_models_after_batch() -> None:
    """Release local ASR/emotion models after one recording batch is done."""
    import src.config as runtime_config

    if getattr(runtime_config, "MLLM_MODEL", "") not in {"multi-modal", "local-audio"}:
        return
    if not getattr(runtime_config, "MULTI_MODAL_UNLOAD_AUDIO_MODEL", True):
        return

    from src.autoslice.mllm_sdk.audio_analyzer import (
        unload_asr_models,
        unload_emotion_model,
    )

    scan_log.info("Unloading local audio models after slice batch")
    unload_asr_models()
    if getattr(runtime_config, "MULTI_MODAL_ENABLE_EMOTION_ANALYSIS", False):
        unload_emotion_model()


def slice_only(video_path):
    """Run the standalone slice pipeline for one completed recording."""
    if not os.path.exists(video_path):
        scan_log.error(f"File {video_path} does not exist.")
        return

    progress = SliceProgressWriter()
    original_video_path = str(video_path)
    source_name = Path(original_video_path).name
    room_id = Path(original_video_path).parent.name
    xml_path = original_video_path[:-4] + ".xml"

    if not os.path.exists(xml_path):
        scan_log.warning(f"No danmaku file for {video_path}, cannot slice by burst.")
        return

    if check_file_size(original_video_path) < MIN_VIDEO_SIZE:
        scan_log.info(
            f"Video size too small ({check_file_size(original_video_path)}MB), "
            f"skip slicing: {original_video_path}"
        )
        return

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
            )

        slices_path = slice_video_by_danmaku(
            xml_path,
            original_video_path,
            return_metadata=True,
            burst_ratio=BURST_RATIO,
            burst_window=BURST_WINDOW,
            burst_context=BURST_CONTEXT,
            burst_merge_gap=BURST_MERGE_GAP,
            burst_top_n=BURST_TOP_N,
            progress_callback=on_slice_progress,
        )
        scan_log.info(f"Generated {len(slices_path)} slices")
    except Exception as e:
        scan_log.error(f"Error in slice_video_by_danmaku: {e}")
        progress.error(str(e))
        return

    total_slices = len(slices_path)
    for index, generated_slice in enumerate(slices_path, start=1):
        slice_path = generated_slice.path
        try:
            progress.update(
                force=True,
                status="running",
                phase="analyze",
                phase_label="分析标题",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                current_slice_percent=100.0,
                message=f"正在分析切片 {index}/{total_slices}",
                error="",
            )
            danmaku_text = extract_danmaku_text(
                xml_path,
                generated_slice.context_start,
                generated_slice.context_end,
            )
            result = generate_title(slice_path, artist, danmaku_text=danmaku_text)

            if result is None:
                scan_log.error(f"Failed to generate title for {slice_path}")
                os.remove(slice_path)
                continue

            from src.autoslice.analysis_result import AnalysisResult

            if isinstance(result, AnalysisResult):
                if not result.retain_recommendation:
                    scan_log.info(
                        f"Slice {slice_path} filtered by LLM judge: "
                        f"retain=False, reason={result.quality_reason}"
                    )
                    os.remove(slice_path)
                    continue

                from src.config import OMNI_ENABLE_DEEP_ANALYSIS

                if OMNI_ENABLE_DEEP_ANALYSIS:
                    analysis_json_path = slice_path[:-4] + "_analysis.json"
                    result.to_json_file(analysis_json_path)
                    scan_log.info(f"Analysis result saved: {analysis_json_path}")

                slice_title = result.title
                slice_desc = result.description
                slice_tags = result.tags
            else:
                slice_title = result
                slice_desc = "精彩直播片段"
                slice_tags = ["直播切片"]

            if isinstance(result, AnalysisResult):
                from src.config import (
                    EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                    EDIT_ENABLE_INSTRUCTION,
                    EDIT_ENABLE_PROMPT_PACKAGE,
                    EDIT_MAX_SUBTITLE_EVIDENCE,
                )
                from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs
                from src.autoslice.edit_instruction import TimeRange

                maybe_write_edit_outputs(
                    analysis=result,
                    source_video=original_video_path,
                    slice_video=slice_path,
                    artist=artist,
                    slice_duration=generated_slice.duration,
                    output_video=slice_path,
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
                current_slice_path=slice_path,
                message="正在写入上传参数",
            )
            write_slice_upload_metadata(
                slice_path,
                title=slice_title,
                desc=slice_desc,
                tag=slice_tags,
                source=f"https://live.bilibili.com/{room_id}",
            )

            progress.update(
                force=True,
                status="running",
                phase="queue",
                phase_label="加入上传队列",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                message="正在加入上传队列",
            )
            if os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1":
                scan_log.info(f"Skip upload queue for local test: {slice_path}")
            elif not insert_upload_queue(slice_path):
                scan_log.error(f"Cannot insert slice to upload queue: {slice_path}")
            else:
                scan_log.info(f"Slice ready for upload: {slice_path}")

        except Exception as e:
            scan_log.error(f"Error processing slice {slice_path}: {e}")
            progress.error(str(e), current_slice=index, total_slices=total_slices)
            if os.path.exists(slice_path):
                os.remove(slice_path)
            delete_slice_upload_metadata(slice_path)

    if total_slices:
        unload_local_audio_models_after_batch()

    if os.getenv("BILIVE_KEEP_SOURCE") == "1":
        scan_log.info("BILIVE_KEEP_SOURCE=1, keep original video/danmaku files.")
    else:
        progress.update(
            force=True,
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="正在清理源文件",
        )
        for remove_path in [original_video_path, xml_path]:
            if os.path.exists(remove_path):
                os.remove(remove_path)
                scan_log.info(f"Removed: {remove_path}")

    progress.complete(
        room_id=room_id,
        source_path=original_video_path,
        source_name=source_name,
        current_slice=total_slices,
        total_slices=total_slices,
    )
    scan_log.info(f"Slice-only processing complete for: {original_video_path}")
