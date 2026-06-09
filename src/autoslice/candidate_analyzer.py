from __future__ import annotations

from typing import Any

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.autoslice.mllm_sdk.audio_analyzer import (
    analyze_audio,
    unload_asr_models,
    unload_emotion_model,
)
from src.autoslice.mllm_sdk.judge import judge_and_title
from src.config import (
    MULTI_MODAL_ENABLE_EMOTION_ANALYSIS,
    MULTI_MODAL_EMOTION_MODEL,
    MULTI_MODAL_UNLOAD_AUDIO_MODEL,
    MULTI_MODAL_WHISPER_MODEL,
    MULTI_MODAL_VISUAL_NAME,
    MULTI_MODAL_VISUAL_URL,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_ENGINE,
)


def analyze_candidate(
    video_path: str,
    artist: str,
    danmaku_text: str,
) -> AnalysisResult:
    try:
        audio = analyze_audio(
            video_path,
            MULTI_MODAL_WHISPER_MODEL,
            enable_emotion=False,
            emotion_model=MULTI_MODAL_EMOTION_MODEL,
            whisper_engine=WHISPER_ENGINE,
            whisper_device=WHISPER_DEVICE,
            whisper_compute_type=WHISPER_COMPUTE_TYPE,
        )
    except Exception as exc:
        return _failed_result(artist, f"ASR failed: {exc}")

    transcript = str(audio.get("transcript") or "").strip()
    if not transcript:
        detail = str(audio.get("error") or "ASR produced no transcript")
        return _failed_result(artist, detail)

    segments = _valid_transcript_segments(audio.get("segments"))
    if not segments:
        return _failed_result(
            artist,
            "ASR produced no valid timestamped transcript segments",
        )

    result = judge_and_title(
        artist=artist,
        danmaku_text=str(danmaku_text or ""),
        transcript=transcript,
        model_url=MULTI_MODAL_VISUAL_URL,
        model_name=MULTI_MODAL_VISUAL_NAME,
    ).to_analysis_result()
    result.transcript = transcript
    result.transcript_segments = segments

    if result.judge_status == "keep" and not str(result.title or "").strip():
        return _failed_result(
            artist,
            "LLM keep response did not include a title",
            transcript=transcript,
            segments=segments,
        )
    return result


def unload_candidate_models() -> None:
    if not MULTI_MODAL_UNLOAD_AUDIO_MODEL:
        return
    unload_asr_models()
    if MULTI_MODAL_ENABLE_EMOTION_ANALYSIS:
        unload_emotion_model()


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


def _failed_result(
    artist: str,
    reason: str,
    *,
    transcript: str = "",
    segments: list[TranscriptSegment] | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        title=f"{artist}候选片段",
        description="等待人工复核",
        tags=["直播切片"],
        quality_score=0.0,
        retain_recommendation=False,
        quality_reason=str(reason),
        judge_status="judge_failed",
        judge_error=str(reason),
        transcript=transcript,
        transcript_segments=list(segments or []),
    )
