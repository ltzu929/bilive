# Copyright (c) 2024 bilive.

import os

from autoslice import slice_video_by_danmaku
from db.conn import insert_upload_queue
from src.autoslice.danmaku_slice import extract_danmaku_text
from src.autoslice.title_generator import generate_title
from src.burn.render_command import render_command
from src.config import (
    AUTO_SLICE,
    BURST_CONTEXT,
    BURST_MERGE_GAP,
    BURST_RATIO,
    BURST_TOP_N,
    BURST_WINDOW,
    MIN_VIDEO_SIZE,
    MODEL_TYPE,
)
from src.danmaku.generate_danmakus import get_resolution, process_danmakus
from src.log.logger import scan_log
from src.subtitle.subtitle_generator import generate_subtitle
from src.upload.extract_video_info import get_video_info
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    write_slice_upload_metadata,
)


def normalize_video_path(filepath):
    """Normalize the video path to upload."""
    parts = filepath.rsplit("/", 1)[-1].split("_")
    date_time_parts = parts[1].split("-")
    new_date_time = (
        f"{date_time_parts[0][:4]}-{date_time_parts[0][4:6]}-"
        f"{date_time_parts[0][6:8]}-{date_time_parts[1]}-{date_time_parts[2]}"
    )
    return filepath.rsplit("/", 1)[0] + "/" + parts[0] + "_" + new_date_time + "-.mp4"


def check_file_size(file_path):
    file_size = os.path.getsize(file_path)
    return file_size / (1024 * 1024)


def render_video(video_path):
    if not os.path.exists(video_path):
        scan_log.error(f"File {video_path} does not exist.")
        return

    original_video_path = str(video_path)
    format_video_path = normalize_video_path(original_video_path)
    xml_path = original_video_path[:-4] + ".xml"
    ass_path = original_video_path[:-4] + ".ass"
    srt_path = original_video_path[:-4] + ".srt"
    jsonl_path = original_video_path[:-4] + ".jsonl"

    try:
        resolution_x, resolution_y = get_resolution(original_video_path)
        subtitle_font_size, subtitle_margin_v = process_danmakus(
            xml_path,
            resolution_x,
            resolution_y,
        )
    except Exception as e:
        scan_log.error(f"Error in process_danmakus: {e}")
        subtitle_font_size = "16"
        subtitle_margin_v = "60"

    if MODEL_TYPE != "pipeline":
        generate_subtitle(original_video_path)

    render_command(
        original_video_path,
        format_video_path,
        subtitle_font_size,
        subtitle_margin_v,
    )
    scan_log.info("Complete danmaku burning and wait for uploading.")

    if AUTO_SLICE and check_file_size(format_video_path) > MIN_VIDEO_SIZE:
        _slice_rendered_video(format_video_path, xml_path, srt_path)

    for remove_path in [original_video_path, xml_path, ass_path, srt_path, jsonl_path]:
        if os.path.exists(remove_path):
            os.remove(remove_path)

    if not insert_upload_queue(format_video_path):
        scan_log.error("Cannot insert the video to the upload queue")


def _slice_rendered_video(format_video_path: str, xml_path: str, srt_path: str) -> None:
    _, artist, _ = get_video_info(format_video_path)
    room_id = os.path.basename(format_video_path).split("_", 1)[0]
    slices_path = slice_video_by_danmaku(
        xml_path,
        format_video_path,
        return_metadata=True,
        burst_ratio=BURST_RATIO,
        burst_window=BURST_WINDOW,
        burst_context=BURST_CONTEXT,
        burst_merge_gap=BURST_MERGE_GAP,
        burst_top_n=BURST_TOP_N,
    )

    for generated_slice in slices_path:
        slice_path = generated_slice.path
        try:
            _prepare_slice_for_upload(
                slice_path,
                generated_slice,
                xml_path,
                srt_path,
                format_video_path,
                artist,
                room_id,
            )
        except Exception as e:
            scan_log.error(f"Error in {slice_path}: {e}")
            delete_slice_upload_metadata(slice_path)


def _prepare_slice_for_upload(
    slice_path,
    generated_slice,
    xml_path,
    srt_path,
    source_video,
    artist,
    room_id,
):
    danmaku_text = extract_danmaku_text(
        xml_path,
        generated_slice.context_start,
        generated_slice.context_end,
    )
    result = generate_title(slice_path, artist, danmaku_text=danmaku_text)
    if result is None:
        scan_log.error(f"Failed to generate title for {slice_path}")
        if os.path.exists(slice_path):
            os.remove(slice_path)
        return

    from src.autoslice.analysis_result import AnalysisResult

    if isinstance(result, AnalysisResult):
        if not _maybe_save_analysis_and_filter(result, slice_path):
            return
        slice_title = result.title
        slice_desc = result.description
        slice_tags = result.tags
        _maybe_write_edit_outputs(result, generated_slice, source_video, slice_path, artist, srt_path)
    else:
        slice_title = result
        slice_desc = "精彩直播片段"
        slice_tags = ["直播切片"]

    write_slice_upload_metadata(
        slice_path,
        title=slice_title,
        desc=slice_desc,
        tag=slice_tags,
        source=f"https://live.bilibili.com/{room_id}",
    )
    if not insert_upload_queue(slice_path):
        scan_log.error("Cannot insert the video to the upload queue")


def _maybe_save_analysis_and_filter(result, slice_path) -> bool:
    from src.autoslice.slice_quality_filter import should_retain_slice
    from src.config import (
        OMNI_ENABLE_DEEP_ANALYSIS,
        OMNI_ENABLE_QUALITY_FILTER,
        OMNI_QUALITY_THRESHOLD,
    )

    if OMNI_ENABLE_DEEP_ANALYSIS:
        analysis_json_path = slice_path[:-4] + "_analysis.json"
        result.to_json_file(analysis_json_path)
        scan_log.info(f"Analysis result saved: {analysis_json_path}")

    if OMNI_ENABLE_QUALITY_FILTER and not should_retain_slice(
        result,
        OMNI_QUALITY_THRESHOLD,
    ):
        scan_log.info(f"Slice {slice_path} filtered by quality, removing")
        os.remove(slice_path)
        delete_slice_upload_metadata(slice_path)
        return False

    return True


def _maybe_write_edit_outputs(result, generated_slice, source_video, slice_path, artist, srt_path):
    from src.autoslice.edit_instruction import TimeRange
    from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs
    from src.config import (
        EDIT_DEFAULT_HIGHLIGHT_WINDOW,
        EDIT_ENABLE_INSTRUCTION,
        EDIT_ENABLE_PROMPT_PACKAGE,
        EDIT_MAX_SUBTITLE_EVIDENCE,
    )

    maybe_write_edit_outputs(
        analysis=result,
        source_video=source_video,
        slice_video=slice_path,
        artist=artist,
        slice_duration=generated_slice.duration,
        subtitle_path=srt_path if os.path.exists(srt_path) else None,
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
