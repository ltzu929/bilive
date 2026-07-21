# Copyright (c) 2024 bilive.

from dataclasses import dataclass
import os
from xml.etree import ElementTree

from .burst_detector import BurstEvent, detect_bursts


def slice_video(*args, **kwargs):
    """Load the ffmpeg-backed slicer only when a slice is executed."""
    from .auto_slice_video.autosv.slice.slice_video import (
        slice_video as implementation,
    )

    return implementation(*args, **kwargs)


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
    """Return video duration in seconds using ffprobe."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def extract_timestamps_from_xml(xml_path: str) -> list[float]:
    """Extract danmaku timestamps from a Bilibili XML file."""
    if not os.path.exists(xml_path):
        return []

    timestamps: list[float] = []
    try:
        for _, elem in ElementTree.iterparse(xml_path, events=("end",)):
            if elem.tag != "d":
                elem.clear()
                continue

            p_attr = elem.attrib.get("p", "")
            try:
                timestamp = float(p_attr.split(",", 1)[0])
            except (ValueError, IndexError):
                elem.clear()
                continue

            timestamps.append(timestamp)
            elem.clear()
    except ElementTree.ParseError:
        return []

    return timestamps


def slice_video_by_danmaku(
    danmaku_path,
    video_path,
    duration=60,
    top_n=1,
    max_overlap=30,
    step=1,
    pre_context=0,
    post_context=0,
    return_metadata=False,
    slice_method="burst",
    burst_ratio=3.0,
    burst_window=10,
    burst_context=60,
    burst_merge_gap=5,
    burst_top_n=3,
    burst_lag_seconds=0.0,
    progress_callback=None,
):
    """Slice a recording by burst detection from Bilibili XML danmaku.

    The legacy density arguments are accepted for backward compatibility, but
    they are ignored because only burst detection is supported.
    """
    output_folder = os.path.abspath(os.path.dirname(video_path))
    video_name = os.path.basename(video_path)
    timestamps = extract_timestamps_from_xml(danmaku_path)

    return _slice_by_burst(
        timestamps,
        video_path,
        output_folder,
        video_name,
        burst_ratio=burst_ratio,
        burst_window=burst_window,
        context=burst_context,
        merge_gap=burst_merge_gap,
        top_n=burst_top_n,
        lag_seconds=burst_lag_seconds,
        return_metadata=return_metadata,
        progress_callback=progress_callback,
    )


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
    lag_seconds=0.0,
    return_metadata=False,
    progress_callback=None,
):
    """Slice around danmaku burst events."""
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
        lag_seconds=lag_seconds,
        diagnostics_callback=lambda summary: _emit_detection_progress(
            progress_callback,
            summary,
        ),
    )

    if not events:
        scan_log.info("No burst events detected, no slices generated")
        return []

    slices_path = []
    total_slices = len(events)
    for index, event in enumerate(events, start=1):
        output_name = os.path.join(
            output_folder,
            f"{format_seconds_for_filename(event.start)}s_{video_name}",
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
            progress_callback=on_ffmpeg_progress if progress_callback else None,
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
            f"Burst slice #{index}: {output_name} "
            f"[{event.start:.1f}s - {event.end:.1f}s] "
            f"ratio={event.burst_ratio:.1f}x danmaku={event.danmaku_count}"
        )

        if return_metadata:
            slices_path.append(_build_generated_slice(output_name, event))
        else:
            slices_path.append(output_name)

    return slices_path


def _build_generated_slice(output_name: str, event: BurstEvent) -> GeneratedSlice:
    return GeneratedSlice(
        path=output_name,
        density_core_start=max(event.start, event.peak_time - 5),
        density_core_end=min(event.end, event.peak_time + 5),
        context_start=event.start,
        context_end=event.end,
        duration=event.duration,
        danmaku_count=event.danmaku_count,
    )


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


def _emit_detection_progress(progress_callback, summary):
    if not progress_callback:
        return
    progress_callback({"event": "detect_complete", **summary})


def _format_timeline_mark(seconds: float) -> str:
    """Format seconds as [mm:ss] for danmaku timeline lines."""
    total = max(0, int(seconds))
    return f"[{total // 60:02d}:{total % 60:02d}]"


def extract_danmaku_text(
    xml_path: str,
    start: float,
    end: float,
    max_chars: int = 500,
    with_timestamps: bool = False,
) -> str:
    """Extract danmaku messages within a time window from a Bilibili XML file.

    When ``with_timestamps`` is False (default), messages are joined by spaces
    and, if too long, truncated to the last ``max_chars`` characters.

    When ``with_timestamps`` is True, each message becomes a ``[mm:ss] text``
    line so the LLM sees the full chronological timeline. If the timeline
    exceeds ``max_chars``, lines are dropped from the middle (keeping the head
    and tail) so both the opening and the climax stay visible.
    """
    if not os.path.exists(xml_path):
        return ""

    messages: list[tuple[float, str]] = []
    try:
        for _, elem in ElementTree.iterparse(xml_path, events=("end",)):
            if elem.tag != "d":
                elem.clear()
                continue
            p_attr = elem.attrib.get("p", "")
            try:
                timestamp = float(p_attr.split(",", 1)[0])
            except (ValueError, IndexError):
                elem.clear()
                continue
            if start <= timestamp <= end:
                text = (elem.text or "").strip()
                if text:
                    messages.append((timestamp, text))
            elem.clear()
    except Exception:
        return ""

    if not with_timestamps:
        result = " ".join(text for _, text in messages)
        if len(result) > max_chars:
            result = result[-max_chars:]
        return result

    messages.sort(key=lambda item: item[0])
    lines = [f"{_format_timeline_mark(ts)} {text}" for ts, text in messages]
    return _truncate_timeline_middle(lines, max_chars)


def _truncate_timeline_middle(lines: list[str], max_chars: int) -> str:
    """Join timeline lines, dropping from the middle when over max_chars."""
    full = "\n".join(lines)
    if len(full) <= max_chars or len(lines) <= 2:
        return full

    marker = "\n…(中间省略)…\n"
    budget = max_chars - len(marker)
    if budget <= 0:
        return full[:max_chars]

    head_budget = budget // 2
    tail_budget = budget - head_budget

    head_lines: list[str] = []
    head_len = 0
    for line in lines:
        add = len(line) + (1 if head_lines else 0)
        if head_len + add > head_budget:
            break
        head_lines.append(line)
        head_len += add

    tail_lines: list[str] = []
    tail_len = 0
    for line in reversed(lines):
        add = len(line) + (1 if tail_lines else 0)
        if tail_len + add > tail_budget:
            break
        tail_lines.insert(0, line)
        tail_len += add

    if not head_lines and not tail_lines:
        return full[:max_chars]

    return "\n".join(head_lines) + marker + "\n".join(tail_lines)
