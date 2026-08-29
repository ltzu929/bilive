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

    result = implementation(*args, **kwargs)
    output_path = args[1] if len(args) > 1 else kwargs.get("output_path")
    if output_path and (
        not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0
    ):
        raise RuntimeError("ffmpeg slicer produced no media")
    return result


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
    burst_start = float(getattr(event, "burst_start", 0.0) or 0.0)
    burst_end = float(getattr(event, "burst_end", 0.0) or 0.0)
    if burst_end <= burst_start:
        burst_start = max(event.start, event.peak_time - 5.0)
        burst_end = min(event.end, event.peak_time + 5.0)
    core_start = max(event.start, min(event.end, burst_start))
    core_end = max(core_start, min(event.end, burst_end))
    return GeneratedSlice(
        path=output_name,
        density_core_start=core_start,
        density_core_end=core_end,
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
    max_chars: int = 4000,
    with_timestamps: bool = True,
    focus_start: float | None = None,
    focus_end: float | None = None,
    relative_to: float | None = None,
) -> str:
    """Extract danmaku messages within a time window from a Bilibili XML file.

    ``relative_to`` shifts emitted timeline coordinates to the candidate
    window's origin while XML filtering still uses absolute source time.

    When ``with_timestamps`` is False, messages are joined by spaces
    and, if too long, truncated to the last ``max_chars`` characters.

    By default each message becomes a ``[mm:ss] text`` line. If the timeline
    exceeds ``max_chars``, 25/50/25 percent of the available budget is reserved
    for the opening, the density focus, and the ending. Callers should pass the
    absolute density-core range as ``focus_start``/``focus_end``. Without an
    explicit focus, the middle tenth of the requested window is used.
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
    offset = float(relative_to or 0.0)
    if offset:
        messages = [
            (timestamp - offset, text)
            for timestamp, text in messages
        ]
        if focus_start is not None:
            focus_start -= offset
        if focus_end is not None:
            focus_end -= offset
    if focus_start is None or focus_end is None or focus_end <= focus_start:
        relative_start = float(start) - offset
        relative_end = float(end) - offset
        midpoint = (relative_start + relative_end) / 2.0
        half_focus = max(1.0, (relative_end - relative_start) * 0.05)
        focus_start = midpoint - half_focus
        focus_end = midpoint + half_focus
    return _truncate_timeline_around_focus(
        messages,
        max_chars,
        float(focus_start),
        float(focus_end),
    )


def _truncate_timeline_around_focus(
    messages: list[tuple[float, str]],
    max_chars: int,
    focus_start: float,
    focus_end: float,
) -> str:
    """Keep chronological head/focus/tail evidence within ``max_chars``."""
    lines = [
        (timestamp, f"{_format_timeline_mark(timestamp)} {text}")
        for timestamp, text in messages
    ]
    full = "\n".join(line for _, line in lines)
    if len(full) <= max_chars:
        return full
    if max_chars <= 0:
        return ""

    head = [line for timestamp, line in lines if timestamp < focus_start]
    focus = [
        line
        for timestamp, line in lines
        if focus_start <= timestamp <= focus_end
    ]
    tail = [line for timestamp, line in lines if timestamp > focus_end]

    # Sparse focus windows still need a useful middle sample.
    if not focus and lines:
        midpoint = (focus_start + focus_end) / 2.0
        nearest_index = min(
            range(len(lines)),
            key=lambda index: abs(lines[index][0] - midpoint),
        )
        focus = [lines[nearest_index][1]]
        head = [line for _, line in lines[:nearest_index]]
        tail = [line for _, line in lines[nearest_index + 1 :]]

    marker = "…(省略)…"
    marker_budget = 2 * (len(marker) + 2)
    content_budget = max(1, max_chars - marker_budget)
    head_lines = _take_timeline_lines(
        head,
        max(1, int(content_budget * 0.25)),
        from_end=False,
    )
    focus_lines = _take_timeline_lines(
        focus,
        max(1, int(content_budget * 0.50)),
        from_end=False,
    )
    tail_lines = _take_timeline_lines(
        tail,
        max(1, content_budget - int(content_budget * 0.75)),
        from_end=True,
    )

    parts = [
        "\n".join(part)
        for part in (head_lines, focus_lines, tail_lines)
        if part
    ]
    if not parts:
        return full[:max_chars]
    result = f"\n{marker}\n".join(parts)
    return result[:max_chars]


def _take_timeline_lines(
    lines: list[str],
    budget: int,
    *,
    from_end: bool,
) -> list[str]:
    """Take complete chronological lines from one side within a char budget."""
    selected: list[str] = []
    used = 0
    source = reversed(lines) if from_end else iter(lines)
    for line in source:
        addition = len(line) + (1 if selected else 0)
        if used + addition > budget:
            break
        selected.append(line)
        used += addition
    if from_end:
        selected.reverse()
    if not selected and lines and budget > 0:
        line = lines[-1] if from_end else lines[0]
        selected = [line[:budget]]
    return selected


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
