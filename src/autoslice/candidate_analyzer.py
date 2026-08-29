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
    MIN_COMPLETENESS_SCORE,
    MIN_CONFIDENCE,
    MIN_QUALITY_SCORE,
    MULTI_MODAL_UNLOAD_AUDIO_MODEL,
    MULTI_MODAL_WHISPER_MODEL,
    SNAP_TRIM_TO_SEGMENTS,
    SNAP_TRIM_TOLERANCE,
    TRIM_ASR_PADDING_SECONDS,
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
    candidate_core_start: float | None = None,
    candidate_core_end: float | None = None,
    single_clip: bool = False,
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
        candidate_start=candidate_start,
        candidate_core_start=candidate_core_start,
        candidate_core_end=candidate_core_end,
        single_clip=single_clip,
    )


def analyze_candidate_clip_results(
    results: list[AnalysisResult],
    video_path: str,
    artist: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
    candidate_core_start: float | None = None,
    candidate_core_end: float | None = None,
    candidate_transcript: str | None = None,
    candidate_transcript_segments: list[TranscriptSegment] | None = None,
    candidate_evidence_error: str = "",
    require_candidate_evidence: bool = False,
    post_judge_asr: bool = False,
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
        if result.judge_status == "review":
            if post_judge_asr and result.suggested_trim is not None:
                error, transcript, segments = _run_post_judge_asr(
                    video_path,
                    result,
                    duration,
                    candidate_core_start,
                    candidate_core_end,
                )
                if error:
                    _append_review_reason(
                        result,
                        f"Post-judgment ASR unavailable: {error}",
                    )
                else:
                    result.transcript = transcript
                    result.transcript_segments = segments
            _annotate_ranges(
                result,
                candidate_start,
                candidate_end,
                duration,
                include_trim=True,
            )
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
        if route_below_quality_gate_to_review(result):
            if post_judge_asr:
                error, transcript, segments = _run_post_judge_asr(
                    video_path,
                    result,
                    duration,
                    candidate_core_start,
                    candidate_core_end,
                )
                if error:
                    _append_review_reason(
                        result,
                        f"Post-judgment ASR unavailable: {error}",
                    )
                else:
                    result.transcript = transcript
                    result.transcript_segments = segments
            _annotate_ranges(
                result,
                candidate_start,
                candidate_end,
                duration,
                include_trim=True,
            )
            analyzed.append(result)
            continue
        if route_trim_shape_to_review(result, duration):
            _annotate_ranges(
                result,
                candidate_start,
                candidate_end,
                duration,
                include_trim=True,
            )
            analyzed.append(result)
            continue

        trim = result.suggested_trim
        assert trim is not None
        evidence_supplied = (
            candidate_transcript is not None
            or candidate_transcript_segments is not None
            or bool(candidate_evidence_error)
        )
        if require_candidate_evidence and not evidence_supplied:
            analyzed.append(
                _failed_result(
                    artist,
                    "Candidate ASR evidence was not prepared before MiMo",
                    base=result,
                )
            )
            continue
        if evidence_supplied:
            if candidate_evidence_error:
                analyzed.append(
                    _failed_result(
                        artist,
                        f"Candidate ASR failed: {candidate_evidence_error}",
                        base=result,
                    )
                )
                continue
            error, transcript, segments = _prepare_evidence_trim(
                result,
                duration,
                candidate_core_start,
                candidate_core_end,
                candidate_transcript_segments or [],
            )
            if error:
                _route_to_review(result, error)
                _annotate_ranges(
                    result,
                    candidate_start,
                    candidate_end,
                    duration,
                    include_trim=True,
                )
                analyzed.append(result)
                continue
        elif post_judge_asr:
            error, transcript, segments = _run_post_judge_asr(
                video_path,
                result,
                duration,
                candidate_core_start,
                candidate_core_end,
            )
            if error:
                analyzed.append(_failed_result(artist, error, base=result))
                continue
        else:
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
    candidate_core_start: float | None = None,
    candidate_core_end: float | None = None,
    candidate_transcript: str | None = None,
    candidate_transcript_segments: list[TranscriptSegment] | None = None,
    candidate_evidence_error: str = "",
    require_candidate_evidence: bool = False,
    single_clip: bool = False,
) -> list[AnalysisResult]:
    results = judge_candidate_clips_only(
        video_path,
        artist,
        danmaku_text,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_duration=candidate_duration,
        candidate_core_start=candidate_core_start,
        candidate_core_end=candidate_core_end,
        single_clip=single_clip,
    )
    return analyze_candidate_clip_results(
        results,
        video_path,
        artist,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_duration=candidate_duration,
        candidate_core_start=candidate_core_start,
        candidate_core_end=candidate_core_end,
        candidate_transcript=candidate_transcript,
        candidate_transcript_segments=candidate_transcript_segments,
        candidate_evidence_error=candidate_evidence_error,
        require_candidate_evidence=require_candidate_evidence,
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
    if route_below_quality_gate_to_review(result):
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=True,
        )
        return result
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


def route_below_quality_gate_to_review(result: AnalysisResult) -> str:
    """Route uncertain MiMo keeps to review before render or upload work.

    Returns the review reason when the gate rejects automatic publishing,
    otherwise an empty string. Explicit MiMo drops and judge failures are left
    unchanged.
    """
    if result.judge_status != "keep" or not result.retain_recommendation:
        return ""

    required = (
        ("quality_score", result.quality_score, MIN_QUALITY_SCORE),
        (
            "completeness_score",
            result.completeness_score,
            MIN_COMPLETENESS_SCORE,
        ),
        ("confidence", result.confidence, MIN_CONFIDENCE),
    )
    failed: list[str] = []
    for name, value, minimum in required:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            failed.append(f"{name}=missing (minimum {minimum:.2f})")
            continue
        if not math.isfinite(numeric) or numeric < float(minimum):
            rendered = "missing" if not math.isfinite(numeric) else f"{numeric:.2f}"
            failed.append(f"{name}={rendered} (minimum {minimum:.2f})")

    if not failed:
        return ""

    reason = "Automatic publish quality gate requires review: " + ", ".join(failed)
    prior_reason = str(result.quality_reason or "").strip()
    result.judge_status = "review"
    result.retain_recommendation = False
    result.judge_error = reason
    result.quality_reason = f"{prior_reason}; {reason}" if prior_reason else reason
    return reason


TRIM_BOUNDARY_REVIEW_SECONDS = 1.0


def route_trim_shape_to_review(
    result: AnalysisResult,
    candidate_duration: float,
    *,
    boundary_seconds: float = TRIM_BOUNDARY_REVIEW_SECONDS,
) -> str:
    """Keep boundary-dependent trims out of automatic previews.

    Trim duration is an editorial preference, not an automatic rejection
    criterion. The current review loop needs to expose longer complete clips
    so a human can judge their actual quality.
    """
    if result.judge_status != "keep" or not result.retain_recommendation:
        return ""
    trim = result.suggested_trim
    if trim is None:
        return ""
    try:
        start = float(trim.trim_start)
        end = float(trim.trim_end)
        duration = float(candidate_duration)
    except (TypeError, ValueError):
        return ""
    if not all(math.isfinite(value) for value in (start, end, duration)):
        return ""

    reasons: list[str] = []
    boundary = max(0.0, float(boundary_seconds))
    if duration > 0 and (start <= boundary or duration - end <= boundary):
        reasons.append(
            "trim is too close to the candidate boundary; context may be incomplete"
        )
    if not reasons:
        return ""

    reason = "Automatic trim gate requires review: " + "; ".join(reasons)
    _route_to_review(result, reason)
    return reason


def _run_asr(video_path: str, start_seconds: float, duration_seconds: float) -> dict:
    return analyze_audio(
        video_path,
        MULTI_MODAL_WHISPER_MODEL,
        whisper_device=WHISPER_DEVICE,
        whisper_compute_type=WHISPER_COMPUTE_TYPE,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )


POST_JUDGE_ASR_PADDING_SECONDS = 20.0


def _transcribe_for_boundary_evidence(
    video_path: str,
    result: AnalysisResult,
    duration: float,
) -> tuple[str, str, list[TranscriptSegment]]:
    """Transcribe only the selected trim plus nearby context.

    MiMo decides whether a candidate is worth keeping. This pass runs after
    that decision and supplies timestamped speech evidence for safe boundaries
    and subtitles; it never participates in candidate discovery.
    """
    trim = result.suggested_trim
    if trim is None:
        return "MiMo keep response did not include a trim interval", "", []

    padding = max(
        float(POST_JUDGE_ASR_PADDING_SECONDS),
        float(TRIM_ASR_PADDING_SECONDS),
    )
    window_start = max(0.0, float(trim.trim_start) - padding)
    window_end = float(trim.trim_end) + padding
    if duration > 0:
        window_end = min(float(duration), window_end)
    if window_end <= window_start:
        return "Post-judgment ASR window is empty", "", []

    try:
        audio = _run_asr(
            video_path,
            window_start,
            window_end - window_start,
        )
    except Exception as exc:
        return f"ASR failed: {exc}", "", []

    window_segments = _valid_transcript_segments(audio.get("segments"))
    candidate_segments = [
        TranscriptSegment(
            start=segment.start + window_start,
            end=segment.end + window_start,
            text=segment.text,
        )
        for segment in window_segments
    ]
    transcript = str(audio.get("transcript") or "").strip()
    if not transcript and candidate_segments:
        transcript = " ".join(segment.text for segment in candidate_segments).strip()
    if not transcript:
        return str(audio.get("error") or "ASR produced no transcript"), "", []
    if not candidate_segments:
        return "ASR produced no valid timestamped transcript segments", "", []
    return "", transcript, candidate_segments


def _run_post_judge_asr(
    video_path: str,
    result: AnalysisResult,
    duration: float,
    candidate_core_start: float | None,
    candidate_core_end: float | None,
) -> tuple[str, str, list[TranscriptSegment]]:
    error, _, segments = _transcribe_for_boundary_evidence(
        video_path,
        result,
        duration,
    )
    if error:
        return error, "", []
    return _prepare_evidence_trim(
        result,
        duration,
        candidate_core_start,
        candidate_core_end,
        segments,
    )


def _append_review_reason(result: AnalysisResult, reason: str) -> None:
    prior_reason = str(result.quality_reason or "").strip()
    result.judge_error = (
        f"{result.judge_error}; {reason}"
        if result.judge_error
        else reason
    )
    result.quality_reason = (
        f"{prior_reason}; {reason}" if prior_reason else reason
    )


def _prepare_evidence_trim(
    result: AnalysisResult,
    duration: float,
    candidate_core_start: float | None,
    candidate_core_end: float | None,
    segments: list[TranscriptSegment],
) -> tuple[str, str, list[TranscriptSegment]]:
    """Validate and repair a keep trim using timestamped ASR evidence."""
    if not segments:
        return "Candidate ASR contains no timestamped segments", "", []

    try:
        core_start = float(result.core_start)
        core_end = float(result.core_end)
    except (TypeError, ValueError):
        return "MiMo keep response did not include a highlight core interval", "", []
    if not all(math.isfinite(value) for value in (core_start, core_end)):
        return "MiMo highlight core interval must be finite", "", []
    if core_start < 0 or core_end <= core_start:
        return "MiMo highlight core interval is empty or reversed", "", []
    if duration > 0 and core_end > duration + 0.001:
        return "MiMo highlight core interval exceeds the candidate duration", "", []

    if candidate_core_start is not None and candidate_core_end is not None:
        try:
            density_start = float(candidate_core_start)
            density_end = float(candidate_core_end)
        except (TypeError, ValueError):
            return "Detected burst core interval is invalid", "", []
        if density_end > density_start and (
            min(core_end, density_end) <= max(core_start, density_start)
        ):
            return "MiMo highlight core does not cover the detected burst", "", []

    trim = result.suggested_trim
    assert trim is not None
    trim_start = min(float(trim.trim_start), core_start)
    trim_end = max(float(trim.trim_end), core_end)
    repaired = TrimSuggestion(
        trim_start=trim_start,
        trim_end=trim_end,
        reason=f"{trim.reason}; ASR boundary repair",
    )
    snapped = snap_trim_to_segments(
        repaired,
        segments,
        max(0.0, float(SNAP_TRIM_TOLERANCE)),
        outward_only=True,
    )
    result.suggested_trim = snapped
    trim_error = _validate_trim(result, duration)
    if trim_error:
        return trim_error, "", []
    if snapped.trim_start > core_start + 0.001 or snapped.trim_end < core_end - 0.001:
        return "Repaired trim does not cover the highlight core", "", []
    if not any(
        segment.start < core_start and segment.end > snapped.trim_start
        for segment in segments
    ):
        return "No ASR evidence before the highlight core inside the trim", "", []
    if not any(
        segment.end > core_end and segment.start < snapped.trim_end
        for segment in segments
    ):
        return "No ASR evidence after the highlight core inside the trim", "", []

    sliced_transcript, sliced_segments = _slice_segments_to_trim(segments, snapped)
    if not sliced_transcript or not sliced_segments:
        return "ASR evidence does not overlap the repaired trim", "", []
    return "", sliced_transcript, sliced_segments


def _route_to_review(result: AnalysisResult, reason: str) -> None:
    prior_reason = str(result.quality_reason or "").strip()
    result.judge_status = "review"
    result.retain_recommendation = False
    result.judge_error = str(reason)
    result.quality_reason = (
        f"{prior_reason}; {reason}" if prior_reason else str(reason)
    )


def _transcribe_for_trim(
    video_path: str,
    result: AnalysisResult,
    duration: float,
) -> tuple[str, str, list[TranscriptSegment]]:
    """Run ASR for the current trim, returning (error, transcript, segments).

    When ``SNAP_TRIM_TO_SEGMENTS`` is enabled, ASR runs over only the requested
    trim plus a bounded padding window. Endpoints are snapped to nearby speech
    segment boundaries and that same transcript is reused for subtitles.
    Snapping is accepted only when the updated trim remains valid.
    """
    trim = result.suggested_trim
    assert trim is not None

    if SNAP_TRIM_TO_SEGMENTS:
        padding = max(0.0, float(TRIM_ASR_PADDING_SECONDS))
        window_start = max(0.0, float(trim.trim_start) - padding)
        window_end = float(trim.trim_end) + padding
        if duration > 0:
            window_end = min(float(duration), window_end)
        try:
            window_audio = _run_asr(
                video_path,
                window_start,
                max(0.0, window_end - window_start),
            )
        except Exception as exc:
            return f"ASR failed: {exc}", "", []
        window_segments = _valid_transcript_segments(
            window_audio.get("segments")
        )
        candidate_segments = [
            TranscriptSegment(
                start=segment.start + window_start,
                end=segment.end + window_start,
                text=segment.text,
            )
            for segment in window_segments
        ]
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
        # The padded ASR produced nothing reusable; fall back to the exact trim.

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
    *,
    outward_only: bool = False,
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
    if outward_only:
        new_start = _snap_start_outward(float(trim.trim_start), starts, tolerance)
        new_end = _snap_end_outward(float(trim.trim_end), ends, tolerance)
    else:
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


def _snap_start_outward(value: float, candidates: list[float], tolerance: float) -> float:
    eligible = [
        candidate
        for candidate in candidates
        if candidate <= value and value - candidate <= tolerance
    ]
    return max(eligible, default=value)


def _snap_end_outward(value: float, candidates: list[float], tolerance: float) -> float:
    eligible = [
        candidate
        for candidate in candidates
        if candidate >= value and candidate - value <= tolerance
    ]
    return min(eligible, default=value)


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
    failed = AnalysisResult(
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
        core_start=base.core_start if base else None,
        core_end=base.core_end if base else None,
        source_start=base.source_start if base else None,
        source_end=base.source_end if base else None,
        transcript=transcript,
        transcript_segments=list(segments or []),
        raw_model_response=(
            dict(base.raw_model_response)
            if base is not None and isinstance(base.raw_model_response, dict)
            else {}
        ),
    )
    if base is not None:
        for attribute in ("_dedupe_key", "duplicate_of", "duplicate_reason"):
            if hasattr(base, attribute):
                setattr(failed, attribute, getattr(base, attribute))
    return failed
