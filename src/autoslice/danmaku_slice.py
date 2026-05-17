# Copyright (c) 2024 bilive.

from dataclasses import dataclass
import os
import re
from xml.etree import ElementTree

from .auto_slice_video.autosv.autosv import extract_timestamps
from .auto_slice_video.autosv.calculate.selection import find_dense_periods
from .auto_slice_video.autosv.log.logger import Log
from .auto_slice_video.autosv.slice.slice_video import slice_video


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
):
    """Slice by danmaku density, optionally expanding dense cores with context."""
    autosv_log = Log("autosv")
    autosv_log.info("autosv v0.0.3")
    autosv_log.info("https://github.com/timerring/auto-slice-video")
    output_folder = os.path.abspath(os.path.dirname(video_path))
    video_name = os.path.basename(video_path)
    timestamps = extract_timestamps(ass_path)
    dense_periods = find_dense_periods(
        autosv_log, timestamps, duration, top_n, max_overlap, step
    )

    autosv_log.info("The dense periods and their count are:")
    slices_path = []
    for period in dense_periods:
        density_start = float(period[0])
        density_end = density_start + float(duration)
        context_start = max(0.0, density_start - float(pre_context))
        context_end = density_end + float(post_context)
        context_duration = context_end - context_start
        output_name = (
            f"{output_folder}/"
            f"{format_seconds_for_filename(context_start)}s_{video_name}"
        )

        autosv_log.info(
            f"Core from {density_start:g} to {density_end:g} seconds "
            f"with the count is {period[1]}; "
            f"context from {context_start:g} to {context_end:g} seconds"
        )
        slice_video(video_path, output_name, context_start, context_duration)
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

