# Copyright (c) 2024 bilive.
# Slice-only pipeline: skip full-stream rendering and generate/upload clips directly.

import os
from pathlib import Path

from src.config import (
    AUTO_SLICE,
    SLICE_DURATION,
    MIN_VIDEO_SIZE,
    SLICE_NUM,
    SLICE_OVERLAP,
    SLICE_POST_CONTEXT,
    SLICE_PRE_CONTEXT,
    SLICE_STEP,
    SLICE_METHOD,
    BURST_RATIO,
    BURST_WINDOW,
    BURST_CONTEXT,
    BURST_MERGE_GAP,
    BURST_TOP_N,
)
from src.danmaku.generate_danmakus import get_resolution, process_danmakus
from autoslice import slice_video_by_danmaku
from src.autoslice.danmaku_slice import extract_danmaku_text
from src.autoslice.inject_metadata import inject_metadata
from src.autoslice.title_generator import generate_title
from src.upload.extract_video_info import get_video_info
from src.log.logger import scan_log
from src.burn.slice_progress import SliceProgressWriter
from db.conn import insert_upload_queue


def check_file_size(file_path):
    """Return file size in MB."""
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    return file_size_mb


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
    ass_path = original_video_path[:-4] + ".ass"

    if not os.path.exists(xml_path):
        scan_log.warning(f"No danmaku file for {video_path}, cannot slice by density.")
        return

    if check_file_size(original_video_path) < MIN_VIDEO_SIZE:
        scan_log.info(
            f"Video size too small ({check_file_size(original_video_path)}MB), "
            f"skip slicing: {original_video_path}"
        )
        return

    scan_log.info(f"Starting slice-only processing: {original_video_path}")
    progress.update(
        status="running",
        phase="start",
        phase_label="开始处理",
        room_id=room_id,
        source_path=original_video_path,
        source_name=source_name,
        current_slice=0,
        total_slices=0,
        current_slice_path="",
        current_slice_percent=0.0,
        message="正在准备切片任务",
        error="",
    )

    try:
        progress.update(
            status="running",
            phase="danmaku",
            phase_label="弹幕转换",
            message="正在转换弹幕",
        )
        resolution_x, resolution_y = get_resolution(original_video_path)
        process_danmakus(xml_path, resolution_x, resolution_y)
        scan_log.info(f"Danmaku converted: {ass_path}")
    except Exception as e:
        scan_log.error(f"Error in process_danmakus: {e}")
        progress.error(str(e))
        return

    progress.update(
        status="running",
        phase="info",
        phase_label="读取信息",
        message="正在读取主播和录制信息",
    )
    title, artist, date = get_video_info(original_video_path)

    try:
        progress.update(
            status="running",
            phase="detect",
            phase_label="检测片段",
            message="正在检测高能片段",
        )

        def on_slice_progress(event):
            current_slice = event.get("current_slice", 0)
            total_slices = event.get("total_slices", 0)
            progress.update(
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
                message=f"正在切第 {current_slice}/{total_slices} 个片段",
                error="",
            )

        slices_path = slice_video_by_danmaku(
            ass_path,
            original_video_path,
            SLICE_DURATION,
            SLICE_NUM,
            SLICE_OVERLAP,
            SLICE_STEP,
            pre_context=SLICE_PRE_CONTEXT,
            post_context=SLICE_POST_CONTEXT,
            return_metadata=True,
            slice_method=SLICE_METHOD,
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
                status="running",
                phase="analyze",
                phase_label="分析标题",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                current_slice_percent=100.0,
                message=f"正在分析第 {index}/{total_slices} 个片段",
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
            else:
                slice_title = result

            slice_video_flv_path = slice_path[:-4] + ".flv"

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
                    output_video=slice_video_flv_path,
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
                status="running",
                phase="metadata",
                phase_label="写入元数据",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_path,
                message="正在注入标题元数据",
            )
            inject_metadata(slice_path, slice_title, slice_video_flv_path)
            os.remove(slice_path)

            progress.update(
                status="running",
                phase="queue",
                phase_label="入上传队列",
                current_slice=index,
                total_slices=total_slices,
                current_slice_path=slice_video_flv_path,
                message="正在加入上传队列",
            )
            if os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1":
                scan_log.info(f"Skip upload queue for local test: {slice_video_flv_path}")
            elif not insert_upload_queue(slice_video_flv_path):
                scan_log.error(f"Cannot insert slice to upload queue: {slice_video_flv_path}")
            else:
                scan_log.info(f"Slice ready for upload: {slice_video_flv_path}")

        except Exception as e:
            scan_log.error(f"Error processing slice {slice_path}: {e}")
            if os.path.exists(slice_path):
                os.remove(slice_path)

    if os.getenv("BILIVE_KEEP_SOURCE") == "1":
        scan_log.info("BILIVE_KEEP_SOURCE=1, keep original video/danmaku files.")
    else:
        progress.update(
            status="running",
            phase="cleanup",
            phase_label="清理源文件",
            message="正在清理源文件",
        )
        for remove_path in [original_video_path, xml_path, ass_path]:
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
