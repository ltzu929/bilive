# Copyright (c) 2024 bilive.

from pathlib import Path
import re
from typing import Iterable, List

import pysrt

from src.autoslice.analysis_result import AnalysisResult
from src.autoslice.edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TrimInstruction,
    UploadSuggestion,
)
from src.log.logger import scan_log


DEFAULT_HIGHLIGHT_WINDOW_SECONDS = 12.0


def infer_slice_start_seconds(slice_video: str) -> float:
    name = Path(slice_video).name
    match = re.match(r"^(\d+(?:\.\d+)?)s_", name)
    if not match:
        return 0.0
    return float(match.group(1))


def clamp_time(value: float, duration: float) -> float:
    return max(0.0, min(float(duration), float(value)))


def read_srt_evidence(
    srt_path: str | Path,
    max_items: int = 6,
    start_offset: float = 0.0,
    duration: float | None = None,
) -> List[SubtitleEvidence]:
    path = Path(srt_path)
    if not path.is_file():
        return []

    try:
        subtitles = pysrt.open(str(path), encoding="utf-8")
    except Exception as exc:
        scan_log.warning(f"Failed to read subtitle evidence from {path}: {exc}")
        return []

    evidence = []
    for item in subtitles:
        text = " ".join(str(item.text).split())
        if not text:
            continue
        start = item.start.ordinal / 1000
        end = item.end.ordinal / 1000
        if duration is not None:
            window_end = start_offset + duration
            if end <= start_offset or start >= window_end:
                continue
            start = max(start, start_offset) - start_offset
            end = min(end, window_end) - start_offset
        evidence.append(
            SubtitleEvidence(
                start=start,
                end=end,
                text=text,
            )
        )
        if len(evidence) >= max_items:
            break

    return evidence


def build_segments(
    analysis: AnalysisResult,
    slice_duration: float,
    default_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> List[EditSegment]:
    segments = []
    for highlight in analysis.highlights:
        start = clamp_time(highlight.start, slice_duration)
        end = clamp_time(highlight.end, slice_duration)
        if end <= start:
            continue
        segments.append(
            EditSegment(
                start=start,
                end=end,
                type="highlight",
                score=max(0.0, min(1.0, float(highlight.score))),
                reason=highlight.desc or "highlight from analysis result",
            )
        )

    if segments:
        return segments

    peak = clamp_time(analysis.emotion_peak_time or 0.0, slice_duration)
    half_window = default_window / 2
    start = clamp_time(peak - half_window, slice_duration)
    end = clamp_time(start + default_window, slice_duration)
    if end <= start:
        end = slice_duration

    return [
        EditSegment(
            start=start,
            end=end,
            type="highlight",
            score=max(0.0, min(1.0, float(analysis.quality_score))),
            reason="fallback highlight window around danmaku-selected slice",
        )
    ]


def build_trim(analysis: AnalysisResult, slice_duration: float) -> TrimInstruction:
    if analysis.suggested_trim is None:
        return TrimInstruction(
            start=0.0,
            end=float(slice_duration),
            reason="keep full slice because no trim suggestion was provided",
        )

    start = clamp_time(analysis.suggested_trim.trim_start, slice_duration)
    end = clamp_time(analysis.suggested_trim.trim_end, slice_duration)
    if end <= start:
        start = 0.0
        end = float(slice_duration)

    return TrimInstruction(
        start=start,
        end=end,
        reason=analysis.suggested_trim.reason,
    )


def build_edit_actions(
    segments: Iterable[EditSegment],
    trim: TrimInstruction,
    subtitle_evidence: List[SubtitleEvidence],
) -> List[str]:
    actions = []
    segment_list = list(segments)
    if segment_list:
        primary = segment_list[0]
        actions.append(
            f"Keep {primary.start:.1f}-{primary.end:.1f} as the main highlight"
        )

    if trim.start > 0:
        actions.append(f"Remove opening 0.0-{trim.start:.1f} seconds")
    if trim.reason:
        actions.append(f"Trim reason: {trim.reason}")

    if not subtitle_evidence:
        actions.append("Subtitle evidence is missing; review transcript manually")

    return actions


def build_edit_instruction(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    slice_duration: float,
    subtitle_evidence: List[SubtitleEvidence] | None = None,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> EditInstruction:
    subtitle_evidence = subtitle_evidence or []
    if not subtitle_evidence and analysis.transcript_segments:
        subtitle_evidence = [
            SubtitleEvidence(start=segment.start, end=segment.end, text=segment.text)
            for segment in analysis.transcript_segments
            if segment.text
        ]
    segments = build_segments(analysis, slice_duration, default_highlight_window)
    trim = build_trim(analysis, slice_duration)
    decision = "keep" if analysis.retain_recommendation else "drop"

    return EditInstruction(
        source_video=str(source_video),
        slice_video=str(slice_video),
        decision=decision,
        confidence=max(0.0, min(1.0, float(analysis.quality_score))),
        trim=trim,
        segments=segments,
        subtitle_evidence=subtitle_evidence,
        danmaku_evidence=DanmakuEvidence(
            peak_time=analysis.emotion_peak_time or infer_slice_start_seconds(slice_video),
            density_reason="slice selected by danmaku density",
        ),
        edit_actions=build_edit_actions(segments, trim, subtitle_evidence),
        upload_suggestion=UploadSuggestion(
            title=analysis.title,
            description=analysis.description,
            tags=analysis.tags,
        ),
    )


def build_and_write_edit_instruction(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    slice_duration: float,
    subtitle_path: str | Path | None = None,
    max_subtitle_evidence: int = 6,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> str | None:
    subtitle_evidence = []
    if subtitle_path:
        subtitle_evidence = read_srt_evidence(
            subtitle_path,
            max_items=max_subtitle_evidence,
            start_offset=infer_slice_start_seconds(slice_video),
            duration=slice_duration,
        )

    instruction = build_edit_instruction(
        analysis=analysis,
        source_video=source_video,
        slice_video=slice_video,
        slice_duration=slice_duration,
        subtitle_evidence=subtitle_evidence,
        default_highlight_window=default_highlight_window,
    )
    output_path = str(Path(slice_video).with_suffix("")) + "_edit.json"
    if instruction.to_json_file(output_path):
        scan_log.info(f"Edit instruction saved: {output_path}")
        return output_path
    return None


def maybe_write_edit_outputs(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    artist: str,
    slice_duration: float,
    subtitle_path: str | Path | None = None,
    output_video: str | None = None,
    enable_edit_instruction: bool = True,
    enable_prompt_package: bool = False,
    max_subtitle_evidence: int = 6,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> str | None:
    if not enable_edit_instruction:
        return None

    try:
        edit_path = build_and_write_edit_instruction(
            analysis=analysis,
            source_video=source_video,
            slice_video=output_video or slice_video,
            slice_duration=slice_duration,
            subtitle_path=subtitle_path,
            max_subtitle_evidence=max_subtitle_evidence,
            default_highlight_window=default_highlight_window,
        )
        if edit_path and enable_prompt_package:
            from src.autoslice.prompt_packager import write_prompt_package

            write_prompt_package(edit_path, artist=artist)
        return edit_path
    except Exception as exc:
        scan_log.error(f"Failed to generate edit outputs for {slice_video}: {exc}")
        return None
