from __future__ import annotations

import math
from typing import Any

from src.autoslice.analysis_result import (
    AnalysisResult,
    TranscriptSegment,
    TrimSuggestion,
)
from src.autoslice.mllm_sdk.audio_analyzer import (
    analyze_audio,
    unload_asr_models,
)
from src.autoslice.mllm_sdk.mimo_video import (
    judge_candidate_clips_with_mimo,
    judge_candidate_with_mimo,
)
from src.config import (
    MULTI_MODAL_UNLOAD_AUDIO_MODEL,
    MULTI_MODAL_WHISPER_MODEL,
    SNAP_TRIM_TO_SEGMENTS,
    SNAP_TRIM_TOLERANCE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
)


def judge_candidate_clips_only(
    video_path: str,
    artist: str,
    danmaku_text: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
) -> list[AnalysisResult]:
    duration = _resolve_candidate_duration(
        candidate_start,
        candidate_end,
        candidate_duration,
    )
    return judge_candidate_clips_with_mimo(
        video_path=video_path,
        artist=artist,
        danmaku_text=str(danmaku_text or ""),
        candidate_duration=duration,
    )


def analyze_candidate_clip_results(
    results: list[AnalysisResult],
    video_path: str,
    artist: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
) -> list[AnalysisResult]:
    duration = _resolve_candidate_duration(
        candidate_start,
        candidate_end,
        candidate_duration,
    )
    analyzed: list[AnalysisResult] = []
    for result in results:
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=False,
        )
        if result.judge_status == "judge_failed":
            analyzed.append(result)
            continue
        if result.judge_status == "drop" or not result.retain_recommendation:
            result.judge_status = "drop"
            result.retain_recommendation = False
            analyzed.append(result)
            continue
        if not str(result.title or "").strip():
            analyzed.append(
                _failed_result(
                    artist,
                    "MiMo keep response did not include a title",
                    base=result,
                )
            )
            continue
        trim_error = _validate_trim(result, duration)
        if trim_error:
            result.suggested_trim = None
            analyzed.append(_failed_result(artist, trim_error, base=result))
            continue

        trim = result.suggested_trim
        assert trim is not None
        error, transcript, segments = _transcribe_for_trim(
            video_path, result, duration
        )
        if error:
            analyzed.append(_failed_result(artist, error, base=result))
            continue
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=True,
        )
        result.transcript = transcript
        result.transcript_segments = segments
        analyzed.append(result)
    return analyzed


def analyze_candidate_clips(
    video_path: str,
    artist: str,
    danmaku_text: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
) -> list[AnalysisResult]:
    results = judge_candidate_clips_only(
        video_path,
        artist,
        danmaku_text,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_duration=candidate_duration,
    )
    return analyze_candidate_clip_results(
        results,
        video_path,
        artist,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_duration=candidate_duration,
    )


def analyze_candidate(
    video_path: str,
    artist: str,
    danmaku_text: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
) -> AnalysisResult:
    duration = _resolve_candidate_duration(
        candidate_start,
        candidate_end,
        candidate_duration,
    )
    result = judge_candidate_with_mimo(
        video_path=video_path,
        artist=artist,
        danmaku_text=str(danmaku_text or ""),
        candidate_duration=duration,
    )
    _annotate_ranges(
        result,
        candidate_start,
        candidate_end,
        duration,
        include_trim=False,
    )

    if result.judge_status == "judge_failed":
        return result
    if result.judge_status == "drop" or not result.retain_recommendation:
        result.judge_status = "drop"
        result.retain_recommendation = False
        return result
    if not str(result.title or "").strip():
        return _failed_result(
            artist,
            "MiMo keep response did not include a title",
            base=result,
        )

    trim_error = _validate_trim(result, duration)
    if trim_error:
        result.suggested_trim = None
        return _failed_result(artist, trim_error, base=result)

    trim = result.suggested_trim
    assert trim is not None
    error, transcript, segments = _transcribe_for_trim(video_path, result, duration)
    if error:
        return _failed_result(artist, error, base=result)
    _annotate_ranges(
        result,
        candidate_start,
        candidate_end,
        duration,
        include_trim=True,
    )

    result.transcript = transcript
    result.transcript_segments = segments
    return result


def unload_candidate_models() -> None:
    if not MULTI_MODAL_UNLOAD_AUDIO_MODEL:
        return
    unload_asr_models()


def _run_asr(video_path: str, start_seconds: float, duration_seconds: float) -> dict:
    return analyze_audio(
        video_path,
        MULTI_MODAL_WHISPER_MODEL,
        whisper_device=WHISPER_DEVICE,
        whisper_compute_type=WHISPER_COMPUTE_TYPE,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )


def _transcribe_for_trim(
    video_path: str,
    result: AnalysisResult,
    duration: float,
) -> tuple[str, str, list[TranscriptSegment]]:
    """Run ASR for the current trim, returning (error, transcript, segments).

    When ``SNAP_TRIM_TO_SEGMENTS`` is enabled, ASR runs once over the whole
    candidate; the trim endpoints are snapped to the nearest sentence
    boundaries and the candidate transcript is reused for the trimmed window
    (avoiding a second ASR pass). Snapping is only accepted when the snapped
    trim still passes ``_validate_trim`` and yields a usable transcript;
    otherwise it falls back to a normal ASR pass over the original trim.
    On success ``result.suggested_trim`` reflects the (possibly snapped) trim.
    """
    trim = result.suggested_trim
    assert trim is not None

    if SNAP_TRIM_TO_SEGMENTS:
        try:
            candidate_audio = _run_asr(video_path, 0.0, float(duration))
        except Exception as exc:
            return f"ASR failed: {exc}", "", []
        candidate_segments = _valid_transcript_segments(
            candidate_audio.get("segments")
        )
        if candidate_segments:
            snapped = snap_trim_to_segments(
                trim, candidate_segments, SNAP_TRIM_TOLERANCE
            )
            original_trim = trim
            result.suggested_trim = snapped
            if _validate_trim(result, duration):
                result.suggested_trim = original_trim
            else:
                trim = snapped
            transcript, segments = _slice_segments_to_trim(
                candidate_segments, trim
            )
            if transcript and segments:
                return "", transcript, segments
        # Candidate ASR produced nothing reusable; fall back to trimmed ASR.

    try:
        audio = _run_asr(
            video_path,
            float(trim.trim_start),
            float(trim.trim_end - trim.trim_start),
        )
    except Exception as exc:
        return f"ASR failed: {exc}", "", []

    transcript = str(audio.get("transcript") or "").strip()
    if not transcript:
        return str(audio.get("error") or "ASR produced no transcript"), "", []
    segments = _valid_transcript_segments(audio.get("segments"))
    if not segments:
        return "ASR produced no valid timestamped transcript segments", "", []
    return "", transcript, segments


def snap_trim_to_segments(
    trim: TrimSuggestion,
    segments: list[TranscriptSegment],
    tolerance: float,
) -> TrimSuggestion:
    """Snap trim endpoints to the nearest sentence boundary within ``tolerance``.

    ``trim`` and ``segments`` are both relative to the candidate start.
    Endpoints without a boundary within ``tolerance`` seconds stay put.
    Returns the original trim if snapping would empty or reverse it.
    """
    if not segments or tolerance <= 0:
        return trim
    starts = [seg.start for seg in segments]
    ends = [seg.end for seg in segments]
    new_start = _snap_value(float(trim.trim_start), starts, tolerance)
    new_end = _snap_value(float(trim.trim_end), ends, tolerance)
    if new_end <= new_start:
        return trim
    return TrimSuggestion(
        trim_start=new_start,
        trim_end=new_end,
        reason=trim.reason,
    )


def _snap_value(value: float, candidates: list[float], tolerance: float) -> float:
    best = value
    best_dist = tolerance
    for candidate in candidates:
        dist = abs(candidate - value)
        if dist <= best_dist:
            best_dist = dist
            best = candidate
    return best


def _slice_segments_to_trim(
    segments: list[TranscriptSegment],
    trim: TrimSuggestion,
) -> tuple[str, list[TranscriptSegment]]:
    """Offset candidate-relative segments into trim-relative segments.

    Segments overlapping ``[trim_start, trim_end]`` are clipped to the window
    and shifted so they are relative to ``trim_start``.
    """
    start = float(trim.trim_start)
    end = float(trim.trim_end)
    window = end - start
    out: list[TranscriptSegment] = []
    for seg in segments:
        if seg.end <= start or seg.start >= end:
            continue
        new_start = max(0.0, seg.start - start)
        new_end = min(window, seg.end - start)
        if new_end <= new_start:
            continue
        out.append(
            TranscriptSegment(start=new_start, end=new_end, text=seg.text)
        )
    transcript = " ".join(seg.text for seg in out).strip()
    return transcript, out


def _valid_transcript_segments(raw_segments: Any) -> list[TranscriptSegment]:
    if not isinstance(raw_segments, list):
        return []

    segments: list[TranscriptSegment] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        try:
            start = max(0.0, float(raw.get("start", 0)))
            end = float(raw.get("end", 0))
        except (TypeError, ValueError):
            continue
        text = str(raw.get("text") or "").strip()
        if not text or end <= start:
            continue
        segments.append(TranscriptSegment(start=start, end=end, text=text))
    return segments


def _resolve_candidate_duration(
    candidate_start: float,
    candidate_end: float | None,
    candidate_duration: float | None,
) -> float:
    if candidate_duration is not None and float(candidate_duration) > 0:
        return float(candidate_duration)
    if candidate_end is not None:
        return max(0.0, float(candidate_end) - float(candidate_start or 0.0))
    return 0.0


def _annotate_ranges(
    result: AnalysisResult,
    candidate_start: float,
    candidate_end: float | None,
    candidate_duration: float,
    *,
    include_trim: bool,
) -> None:
    start = float(candidate_start or 0.0)
    end = (
        float(candidate_end)
        if candidate_end is not None
        else start + float(candidate_duration or 0.0)
    )
    result.candidate_start = start
    result.candidate_end = end
    trim = result.suggested_trim
    if include_trim and trim is not None:
        result.source_start = start + float(trim.trim_start)
        result.source_end = start + float(trim.trim_end)
    else:
        result.source_start = start
        result.source_end = end


def _validate_trim(result: AnalysisResult, candidate_duration: float) -> str:
    trim = result.suggested_trim
    if trim is None:
        return "MiMo keep response did not include a trim interval"
    try:
        start = float(trim.trim_start)
        end = float(trim.trim_end)
        duration = float(candidate_duration)
    except (TypeError, ValueError):
        return "MiMo trim interval is not numeric"
    if not all(math.isfinite(value) for value in (start, end, duration)):
        return "MiMo trim interval and candidate duration must be finite"
    if start < 0:
        return "MiMo trim interval starts before the candidate"
    if duration > 0 and end > duration + 0.001:
        return "MiMo trim interval exceeds the candidate duration"
    if end <= start:
        return "MiMo trim interval is empty or reversed"
    if end - start < 5.0:
        return "MiMo trim interval is shorter than 5 seconds"
    return ""


def _failed_result(
    artist: str,
    reason: str,
    *,
    transcript: str = "",
    segments: list[TranscriptSegment] | None = None,
    base: AnalysisResult | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        title=(base.title if base and base.title else f"{artist} candidate"),
        description=(
            base.description if base and base.description else "Pending manual review"
        ),
        tags=(list(base.tags) if base else ["live"]),
        quality_score=0.0,
        retain_recommendation=False,
        quality_reason=str(reason),
        judge_status="judge_failed",
        judge_error=str(reason),
        model_name=base.model_name if base else "",
        token_usage=dict(base.token_usage) if base else {},
        suggested_trim=base.suggested_trim if base else None,
        candidate_start=base.candidate_start if base else None,
        candidate_end=base.candidate_end if base else None,
        source_start=base.source_start if base else None,
        source_end=base.source_end if base else None,
        transcript=transcript,
        transcript_segments=list(segments or []),
    )
