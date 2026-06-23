"""Audio transcription for the production candidate pipeline."""

from __future__ import annotations

import gc
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from src.log.logger import scan_log


_whisper_model = None
_whisper_model_key: tuple[str, str, str] | None = None

_EXCITED_WORDS = re.compile(r"哈哈|好棒|太强了|厉害|牛逼|太好了|开心|666|绝了")
_FILLER_WORDS = re.compile(r"嗯|额|然后|就是|那个|这个|一个|的话|对吧")
_STOPWORDS = set("的了是在我你他她它们这那个一不就能着过又很都也还让被把向从与而为及但虽却")


def normalize_transcript(text: str) -> str:
    if not text:
        return ""
    try:
        from zhconv import convert

        text = convert(text, "zh-cn")
    except Exception:
        pass
    text = text.replace("\ufffd", "")
    text = re.sub(r"[\uac00-\ud7af\u3130-\u318f\u1100-\u11ff]+", "", text)
    text = re.sub(r"[A-Za-z]{2,}", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"([。！？!?])\1+", r"\1", text)
    return text.strip()


def format_transcript_segments(
    segments: list[dict[str, Any]],
    fallback_text: str = "",
) -> str:
    if not segments:
        return normalize_transcript(fallback_text)

    parts: list[str] = []
    chars_since_sentence = 0
    for index, segment in enumerate(segments):
        text = normalize_transcript(str(segment.get("text") or "")).rstrip(
            "，、。！？!?"
        )
        if not text:
            continue
        chars_since_sentence += len(text)
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        gap = 0.0
        if next_segment:
            gap = float(next_segment.get("start", 0) or 0) - float(
                segment.get("end", 0) or 0
            )
        punctuation = "。" if not next_segment or gap >= 0.8 or chars_since_sentence >= 36 else "，"
        if punctuation == "。":
            chars_since_sentence = 0
        parts.append(f"{text}{punctuation}")
    return "".join(parts).strip() or normalize_transcript(fallback_text)


def extract_audio(
    video_path: str,
    *,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> str:
    temp_dir = Path(tempfile.mkdtemp(prefix="bilive_audio_"))
    audio_path = temp_dir / "audio.wav"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start_seconds is not None and float(start_seconds) > 0:
        command.extend(["-ss", f"{float(start_seconds):.3f}"])
    command.extend([
        "-i",
        str(video_path),
    ])
    if duration_seconds is not None and float(duration_seconds) > 0:
        command.extend(["-t", f"{float(duration_seconds):.3f}"])
    command.extend([
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ])
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=3600)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        scan_log.error(f"ffmpeg audio extraction failed: {exc}")
        return ""
    return str(audio_path)


def transcribe_audio_whisper(
    audio_path: str,
    model_size: str = "large-v3",
    device: str = "cpu",
    engine: str = "faster-whisper",
    compute_type: str | None = None,
) -> dict[str, Any]:
    if engine != "faster-whisper":
        raise ValueError("Only faster-whisper is supported")

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed") from exc

    global _whisper_model, _whisper_model_key
    resolved_compute_type = compute_type or ("int8" if device == "cpu" else "float16")
    model_key = (model_size, device, resolved_compute_type)
    try:
        if _whisper_model is None or _whisper_model_key != model_key:
            _whisper_model = WhisperModel(
                model_size,
                device=device,
                compute_type=resolved_compute_type,
            )
            _whisper_model_key = model_key
        segment_iter, info = _whisper_model.transcribe(audio_path, language="zh")
        segments = [
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": normalize_transcript(segment.text),
            }
            for segment in segment_iter
        ]
        return {
            "transcript": format_transcript_segments(segments),
            "segments": segments,
            "language": getattr(info, "language", "zh"),
        }
    except Exception as exc:
        scan_log.error(f"faster-whisper transcription failed: {exc}")
        return {"transcript": "", "segments": [], "error": str(exc)}


def extract_keywords(text: str, max_keywords: int = 5) -> list[str]:
    phrases: Counter[str] = Counter()
    for width in range(2, 5):
        for index in range(len(text) - width + 1):
            value = text[index : index + width]
            if re.fullmatch(r"[\u4e00-\u9fff]+", value) and not any(
                char in _STOPWORDS for char in value
            ):
                phrases[value] += 1

    result: list[str] = []
    for value, _count in phrases.most_common():
        if any(value in existing or existing in value for existing in result):
            continue
        result.append(value)
        if len(result) >= max_keywords:
            break
    return result


def detect_emotion(text: str) -> str:
    for emotion, keywords in {
        "excited": ["哈哈", "好棒", "太强了", "厉害", "牛逼", "太好了", "开心"],
        "happy": ["谢谢", "喜欢", "快乐", "幸福", "可爱"],
        "angry": ["生气", "讨厌", "烦人", "无语", "气死"],
        "sad": ["难过", "伤心", "遗憾", "可惜", "哭"],
        "calm": ["好的", "明白", "清楚", "理解"],
    }.items():
        if any(keyword in text for keyword in keywords):
            return emotion
    return "neutral"


def analyze_audio_content(transcript: str) -> dict[str, Any]:
    if not transcript or len(transcript) < 10:
        return {
            "audio_theme": "未知",
            "audio_emotion": "neutral",
            "audio_keywords": [],
            "audio_quality": 0.3,
            "audio_highlights": [],
        }
    emotional_density = min(
        len(_EXCITED_WORDS.findall(transcript)) / max(len(transcript) / 10, 1),
        1.0,
    )
    filler_density = min(
        len(_FILLER_WORDS.findall(transcript)) / max(len(transcript) / 10, 1),
        1.0,
    )
    informative = re.sub(r"[嗯额的了在着过又很都也还，。！？!?]", "", transcript)
    information_density = len(informative) / max(len(transcript), 1)
    quality = max(0.1, min(1.0, 0.5 + emotional_density * 0.3 - filler_density * 0.3))
    if information_density < 0.3:
        quality = min(quality, 0.4)
    return {
        "audio_theme": "直播内容",
        "audio_emotion": detect_emotion(transcript),
        "audio_keywords": extract_keywords(transcript),
        "audio_quality": quality,
        "audio_highlights": [],
    }


def cleanup_audio(audio_path: str) -> None:
    if audio_path:
        shutil.rmtree(Path(audio_path).parent, ignore_errors=True)


def release_gpu_memory(delay: float = 3.0) -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass
    if delay > 0:
        time.sleep(delay)


def unload_asr_models() -> None:
    global _whisper_model, _whisper_model_key
    _whisper_model = None
    _whisper_model_key = None
    release_gpu_memory()


def unload_whisper_model() -> None:
    unload_asr_models()


def analyze_audio(
    video_path: str,
    whisper_model: str = "large-v3",
    *,
    whisper_device: str = "cpu",
    whisper_compute_type: str | None = "int8",
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    audio_path = extract_audio(
        video_path,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )
    if not audio_path:
        return {
            "transcript": "",
            "segments": [],
            "error": "audio_extraction_failed",
        }
    try:
        return transcribe_audio_whisper(
            audio_path,
            whisper_model,
            device=whisper_device,
            engine="faster-whisper",
            compute_type=whisper_compute_type,
        )
    finally:
        cleanup_audio(audio_path)
