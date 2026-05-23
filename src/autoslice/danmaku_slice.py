# Copyright (c) 2024 bilive.

from dataclasses import dataclass
import os
import re
from xml.etree import ElementTree

from .auto_slice_video.autosv.autosv import extract_timestamps
from .auto_slice_video.autosv.calculate.selection import find_dense_periods
from .auto_slice_video.autosv.log.logger import Log
from .auto_slice_video.autosv.slice.slice_video import slice_video
from .burst_detector import detect_bursts, BurstEvent


@dataclass
class GeneratedSlice:
    path: str
    density_core_start: float
    density_core_end: float
    context_start: float
    context_end: float
    duration: float
    danmaku_count: int


def format_seconds_for_filename(seconds: float) -> str:
    seconds = float(seconds)
    if seconds.is_integer():
        return str(int(seconds))
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def _get_video_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长（秒）"""
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def slice_video_by_danmaku(
    ass_path,
    video_path,
    duration=60,
    top_n=1,
    max_overlap=30,
    step=1,
    pre_context=0,
    post_context=0,
    return_metadata=False,
    # burst 模式参数
    slice_method="density",
    burst_ratio=3.0,
    burst_window=10,
    burst_context=60,
    burst_merge_gap=5,
    burst_top_n=3,
    progress_callback=None,
):
    """Slice by danmaku density or burst detection.

    Args:
        slice_method: "density" (旧算法) 或 "burst" (突增检测)
        burst_ratio: 突增阈值（局部密度/背景密度）
        burst_window: 突增检测窗口大小（秒）
        burst_context: 峰值前后各取的秒数
        burst_merge_gap: 相邻突增合并间隔（秒）
        burst_top_n: 最多选几个突增事件
    """
    output_folder = os.path.abspath(os.path.dirname(video_path))
    video_name = os.path.basename(video_path)
    timestamps = extract_timestamps(ass_path)

    if slice_method == "burst":
        return _slice_by_burst(
            timestamps, video_path, output_folder, video_name,
            burst_ratio=burst_ratio,
            burst_window=burst_window,
            context=burst_context,
            merge_gap=burst_merge_gap,
            top_n=burst_top_n,
            return_metadata=return_metadata,
            progress_callback=progress_callback,
        )

    # 旧算法：density 模式
    autosv_log = Log("autosv")
    autosv_log.info("autosv v0.0.3")
    autosv_log.info("https://github.com/timerring/auto-slice-video")
    dense_periods = find_dense_periods(
        autosv_log, timestamps, duration, top_n, max_overlap, step
    )

    autosv_log.info("The dense periods and their count are:")
    slices_path = []
    total_slices = len(dense_periods)
    for index, period in enumerate(dense_periods, start=1):
        density_start = float(period[0])
        density_end = density_start + float(duration)
        context_start = max(0.0, density_start - float(pre_context))
        context_end = density_end + float(post_context)
        context_duration = context_end - context_start
        output_name = os.path.join(
            output_folder,
            f"{format_seconds_for_filename(context_start)}s_{video_name}",
        )

        autosv_log.info(
            f"Core from {density_start:g} to {density_end:g} seconds "
            f"with the count is {period[1]}; "
            f"context from {context_start:g} to {context_end:g} seconds"
        )
        _emit_slice_progress(
            progress_callback,
            "slice_start",
            index,
            total_slices,
            output_name,
            0.0,
        )

        def on_ffmpeg_progress(percent, idx=index, total=total_slices, path=output_name):
            _emit_slice_progress(
                progress_callback,
                "slice_progress",
                idx,
                total,
                path,
                percent,
            )

        if progress_callback:
            slice_video(
                video_path,
                output_name,
                context_start,
                context_duration,
                progress_callback=on_ffmpeg_progress,
            )
        else:
            slice_video(video_path, output_name, context_start, context_duration)
        _emit_slice_progress(
            progress_callback,
            "slice_complete",
            index,
            total_slices,
            output_name,
            100.0,
        )
        autosv_log.info(f"Slice the {output_name} done.")

        if return_metadata:
            slices_path.append(
                GeneratedSlice(
                    path=output_name,
                    density_core_start=density_start,
                    density_core_end=density_end,
                    context_start=context_start,
                    context_end=context_end,
                    duration=context_duration,
                    danmaku_count=int(period[1]),
                )
            )
        else:
            slices_path.append(output_name)

    return slices_path


def _slice_by_burst(
    timestamps,
    video_path,
    output_folder,
    video_name,
    burst_ratio=3.0,
    burst_window=10,
    context=60,
    merge_gap=5,
    top_n=3,
    return_metadata=False,
    progress_callback=None,
):
    """突增检测模式：基于弹幕突增率找切片点"""
    from src.log.logger import scan_log

    video_duration = _get_video_duration(video_path)
    if video_duration <= 0:
        scan_log.warning(f"Cannot get video duration for {video_path}")
        return []

    events = detect_bursts(
        timestamps=timestamps,
        video_duration=video_duration,
        burst_ratio=burst_ratio,
        burst_window=burst_window,
        context=context,
        merge_gap=merge_gap,
        top_n=top_n,
    )

    if not events:
        scan_log.info("No burst events detected, no slices generated")
        return []

    slices_path = []
    total_slices = len(events)
    for i, event in enumerate(events):
        index = i + 1
        output_name = (
            f"{output_folder}/"
            f"{format_seconds_for_filename(event.start)}s_{video_name}"
        )
        _emit_slice_progress(
            progress_callback,
            "slice_start",
            index,
            total_slices,
            output_name,
            0.0,
        )

        def on_ffmpeg_progress(percent, idx=index, total=total_slices, path=output_name):
            _emit_slice_progress(
                progress_callback,
                "slice_progress",
                idx,
                total,
                path,
                percent,
            )

        slice_video(
            video_path,
            output_name,
            event.start,
            event.duration,
            progress_callback=on_ffmpeg_progress,
        )
        _emit_slice_progress(
            progress_callback,
            "slice_complete",
            index,
            total_slices,
            output_name,
            100.0,
        )
        scan_log.info(
            f"Burst slice #{i+1}: {output_name} "
            f"[{event.start:.1f}s - {event.end:.1f}s] "
            f"ratio={event.burst_ratio:.1f}x danmaku={event.danmaku_count}"
        )

        if return_metadata:
            slices_path.append(
                GeneratedSlice(
                    path=output_name,
                    density_core_start=event.peak_time - 5,  # 近似 core start
                    density_core_end=event.peak_time + 5,    # 近似 core end
                    context_start=event.start,
                    context_end=event.end,
                    duration=event.duration,
                    danmaku_count=event.danmaku_count,
                )
            )
        else:
            slices_path.append(output_name)

    return slices_path


def _emit_slice_progress(
    progress_callback,
    event,
    current_slice,
    total_slices,
    output_path,
    percent,
):
    if not progress_callback:
        return
    progress_callback(
        {
            "event": event,
            "current_slice": current_slice,
            "total_slices": total_slices,
            "output_path": output_path,
            "percent": percent,
        }
    )


def extract_danmaku_text(xml_path: str, start: float, end: float,
                         max_chars: int = 500) -> str:
    """Extract danmaku messages within a time window from a Bilibili XML file.

    Args:
        xml_path: Path to the .xml danmaku file.
        start: Start time in seconds.
        end: End time in seconds.
        max_chars: Maximum total characters to return (truncates oldest first).

    Returns:
        Space-joined danmaku text within the time window.
    """
    if not os.path.exists(xml_path):
        return ""

    messages = []
    try:
        for event, elem in ElementTree.iterparse(xml_path):
            if elem.tag != "d":
                continue
            p_attr = elem.attrib.get("p", "")
            if not p_attr:
                continue
            try:
                timestamp = float(p_attr.split(",")[0])
            except (ValueError, IndexError):
                continue
            if start <= timestamp <= end:
                text = (elem.text or "").strip()
                if text:
                    messages.append(text)
            elem.clear()
    except Exception:
        return ""

    # Truncate to max_chars (remove oldest first to keep recent context)
    result = " ".join(messages)
    if len(result) > max_chars:
        result = result[-max_chars:]

    return result
