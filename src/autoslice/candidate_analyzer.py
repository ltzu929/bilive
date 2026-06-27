from __future__ import annotations

import math
from typing import Any

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
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
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=True,
        )
        try:
            audio = analyze_audio(
                video_path,
                MULTI_MODAL_WHISPER_MODEL,
                whisper_device=WHISPER_DEVICE,
                whisper_compute_type=WHISPER_COMPUTE_TYPE,
                start_seconds=float(trim.trim_start),
                duration_seconds=float(trim.trim_end - trim.trim_start),
            )
        except Exception as exc:
            analyzed.append(_failed_result(artist, f"ASR failed: {exc}", base=result))
            continue

        transcript = str(audio.get("transcript") or "").strip()
        if not transcript:
            detail = str(audio.get("error") or "ASR produced no transcript")
            analyzed.append(_failed_result(artist, detail, base=result))
            continue
        segments = _valid_transcript_segments(audio.get("segments"))
        if not segments:
            analyzed.append(
                _failed_result(
                    artist,
                    "ASR produced no valid timestamped transcript segments",
                    base=result,
                )
            )
            continue
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
    _annotate_ranges(
        result,
        candidate_start,
        candidate_end,
        duration,
        include_trim=True,
    )
    try:
        audio = analyze_audio(
            video_path,
            MULTI_MODAL_WHISPER_MODEL,
            whisper_device=WHISPER_DEVICE,
            whisper_compute_type=WHISPER_COMPUTE_TYPE,
            start_seconds=float(trim.trim_start),
            duration_seconds=float(trim.trim_end - trim.trim_start),
        )
    except Exception as exc:
        return _failed_result(artist, f"ASR failed: {exc}", base=result)

    transcript = str(audio.get("transcript") or "").strip()
    if not transcript:
        detail = str(audio.get("error") or "ASR produced no transcript")
        return _failed_result(artist, detail, base=result)

    segments = _valid_transcript_segments(audio.get("segments"))
    if not segments:
        return _failed_result(
            artist,
            "ASR produced no valid timestamped transcript segments",
            base=result,
        )

    result.transcript = transcript
    result.transcript_segments = segments
    return result


def unload_candidate_models() -> None:
    if not MULTI_MODAL_UNLOAD_AUDIO_MODEL:
        return
    unload_asr_models()


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
