from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion
from src.config import (
    MIMO_BASE_URL,
    MIMO_FPS,
    MIMO_MAX_BASE64_BYTES,
    MIMO_MEDIA_RESOLUTION,
    MIMO_MODEL,
    MIMO_TIMEOUT,
)
from src.log.logger import scan_log


RunCommand = Callable[..., Any]


class MimoVideoTooLarge(RuntimeError):
    pass


@dataclass
class EncodedMimoVideo:
    url: str
    base64_bytes: int


_status_lock = threading.Lock()
_status: dict[str, Any] = {
    "status": "idle",
    "provider": MIMO_MODEL,
    "last_error": "",
}


def mimo_status() -> dict[str, Any]:
    with _status_lock:
        return dict(_status)


def _set_status(status: str, *, error: str = "") -> None:
    with _status_lock:
        _status.update(
            {
                "status": status,
                "provider": MIMO_MODEL,
                "last_error": error,
            }
        )


def encode_video_for_mimo(
    video_path: str | Path,
    *,
    max_base64_bytes: int = MIMO_MAX_BASE64_BYTES,
    run: RunCommand = subprocess.run,
    temporary_directory=tempfile.TemporaryDirectory,
) -> EncodedMimoVideo:
    """Return a Base64 data URL for a temporary 720p H.264/AAC copy."""

    attempts = [
        ("900k", "96k"),
        ("450k", "64k"),
    ]
    last_size = 0
    with temporary_directory(prefix="bilive_mimo_") as temp_dir:
        temp_root = Path(temp_dir)
        for index, (video_bitrate, audio_bitrate) in enumerate(attempts, start=1):
            output = temp_root / f"analysis_{index}.mp4"
            command = _ffmpeg_analysis_copy_command(
                video_path,
                output,
                video_bitrate=video_bitrate,
                audio_bitrate=audio_bitrate,
            )
            run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=3600,
            )
            encoded = base64.b64encode(output.read_bytes())
            last_size = len(encoded)
            if last_size <= int(max_base64_bytes):
                return EncodedMimoVideo(
                    url=f"data:video/mp4;base64,{encoded.decode('ascii')}",
                    base64_bytes=last_size,
                )
            scan_log.warning(
                "MiMo analysis copy base64 payload is too large "
                f"({last_size} bytes), retrying with lower bitrate"
            )
    raise MimoVideoTooLarge(
        "MiMo base64 payload exceeds "
        f"{int(max_base64_bytes)} bytes after retry (last={last_size})"
    )


def _ffmpeg_analysis_copy_command(
    video_path: str | Path,
    output_path: str | Path,
    *,
    video_bitrate: str,
    audio_bitrate: str,
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "scale=-2:720",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        video_bitrate,
        "-maxrate",
        video_bitrate,
        "-bufsize",
        _double_bitrate(video_bitrate),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _double_bitrate(value: str) -> str:
    if value.endswith("k"):
        return f"{int(value[:-1]) * 2}k"
    return value


def judge_candidate_with_mimo(
    *,
    video_path: str,
    artist: str,
    danmaku_text: str,
    candidate_duration: float,
    model: str = MIMO_MODEL,
    base_url: str = MIMO_BASE_URL,
    fps: float = MIMO_FPS,
    media_resolution: str = MIMO_MEDIA_RESOLUTION,
    timeout: float = MIMO_TIMEOUT,
    max_base64_bytes: int = MIMO_MAX_BASE64_BYTES,
    client_factory=OpenAI,
    encoder: Callable[..., EncodedMimoVideo] = encode_video_for_mimo,
) -> AnalysisResult:
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        reason = "MIMO_API_KEY is not set"
        _set_status("error", error=reason)
        return _failed_result(artist, reason, model=model)

    try:
        encoded = encoder(video_path, max_base64_bytes=max_base64_bytes)
        client = client_factory(api_key=api_key, base_url=base_url)
        _set_status("requesting")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You judge livestream highlight candidates. "
                        "Use video frames, audio, danmaku text, and timing together. "
                        "Return only one JSON object."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": encoded.url},
                            "fps": float(fps),
                            "media_resolution": str(media_resolution),
                        },
                        {
                            "type": "text",
                            "text": _build_prompt(
                                artist=artist,
                                danmaku_text=danmaku_text,
                                candidate_duration=candidate_duration,
                            ),
                        },
                    ],
                },
            ],
            max_completion_tokens=1024,
            timeout=timeout,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception as exc:
        reason = f"MiMo failed: {exc}"
        _set_status("error", error=reason)
        scan_log.warning(reason)
        return _failed_result(artist, reason, model=model)

    try:
        if not completion.choices:
            raise ValueError("MiMo response did not include any choices")
        message = completion.choices[0].message
        parsed = _extract_json(str(getattr(message, "content", "") or ""))
        if parsed is None:
            raise ValueError("MiMo JSON parse failed")
        result = _analysis_from_mimo_dict(parsed, artist=artist, model=model)
        result.token_usage = _usage_to_dict(getattr(completion, "usage", None))
        result.model_name = str(getattr(completion, "model", model) or model)
    except Exception as exc:
        reason = f"MiMo response failed: {exc}"
        _set_status("error", error=reason)
        return _failed_result(artist, reason, model=model)

    if result.judge_status == "judge_failed":
        _set_status("error", error=result.judge_error)
    else:
        _set_status("idle")
    return result


def _build_prompt(*, artist: str, danmaku_text: str, candidate_duration: float) -> str:
    return (
        "Candidate metadata:\n"
        f"- streamer: {artist or 'unknown'}\n"
        f"- candidate_duration_seconds: {float(candidate_duration or 0):.3f}\n"
        f"- danmaku_window: {str(danmaku_text or '').strip() or '(none)'}\n\n"
        "Task:\n"
        "Decide whether this candidate should be uploaded. Use the actual video, "
        "audio, danmaku reaction, and whether the moment is understandable as a "
        "short clip. If keeping it, choose exactly one continuous rough-trim "
        "interval inside the candidate. Return JSON with exactly these required "
        "keys: decision (keep or drop), reason, title, description, tags, "
        "quality_score, trim_start, trim_end. quality_score must be a number "
        "from 0 to 1. tags must be an array of strings. For keep, title and "
        "description must be non-empty and trim_start/trim_end must be numeric "
        "seconds relative to the beginning of the candidate video. For drop, "
        "set trim_start and trim_end to null."
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _analysis_from_mimo_dict(
    data: dict[str, Any],
    *,
    artist: str,
    model: str,
) -> AnalysisResult:
    required = {
        "decision",
        "reason",
        "title",
        "description",
        "tags",
        "quality_score",
        "trim_start",
        "trim_end",
    }
    missing = sorted(required.difference(data))
    if missing:
        return _failed_result(
            artist,
            f"MiMo response missing required fields: {', '.join(missing)}",
            model=model,
        )

    decision = str(data.get("decision") or "").strip().lower()
    if decision not in {"keep", "drop"}:
        return _failed_result(
            artist,
            "MiMo response decision must be keep or drop",
            model=model,
        )
    retain = decision == "keep"
    reason_value = data.get("reason")
    if not isinstance(reason_value, str) or not reason_value.strip():
        return _failed_result(
            artist,
            "MiMo response reason must be a non-empty string",
            model=model,
        )
    reason = reason_value.strip()

    title_value = data.get("title")
    description_value = data.get("description")
    if not isinstance(title_value, str):
        return _failed_result(
            artist,
            "MiMo response title must be a string",
            model=model,
        )
    if not isinstance(description_value, str):
        return _failed_result(
            artist,
            "MiMo response description must be a string",
            model=model,
        )
    if retain and not title_value.strip():
        return _failed_result(
            artist,
            "MiMo keep response title must be non-empty",
            model=model,
        )
    if retain and not description_value.strip():
        return _failed_result(
            artist,
            "MiMo keep response description must be non-empty",
            model=model,
        )

    tags = data.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        return _failed_result(
            artist,
            "MiMo response tags must be an array of strings",
            model=model,
        )

    try:
        quality_score = float(data.get("quality_score"))
    except (TypeError, ValueError):
        return _failed_result(
            artist,
            "MiMo response quality_score must be numeric",
            model=model,
        )
    if not math.isfinite(quality_score) or not 0.0 <= quality_score <= 1.0:
        return _failed_result(
            artist,
            "MiMo response quality_score must be between 0 and 1",
            model=model,
        )

    trim = None
    if retain:
        try:
            trim_start = float(data.get("trim_start"))
            trim_end = float(data.get("trim_end"))
            if not math.isfinite(trim_start) or not math.isfinite(trim_end):
                raise ValueError("trim values must be finite")
            trim = TrimSuggestion(
                trim_start=trim_start,
                trim_end=trim_end,
                reason=reason,
            )
        except (TypeError, ValueError):
            return _failed_result(
                artist,
                "MiMo keep response trim values must be finite numbers",
                model=model,
            )
    elif data.get("trim_start") is not None or data.get("trim_end") is not None:
        return _failed_result(
            artist,
            "MiMo drop response trim_start and trim_end must be null",
            model=model,
        )

    return AnalysisResult(
        title=title_value.strip(),
        description=description_value.strip(),
        tags=[tag.strip() for tag in tags if tag.strip()],
        retain_recommendation=retain,
        quality_reason=reason,
        quality_score=quality_score,
        judge_status="keep" if retain else "drop",
        judge_error="",
        suggested_trim=trim,
        model_name=model,
    )


def _analysis_list_from_mimo_dict(
    data: dict[str, Any],
    *,
    artist: str,
    model: str,
) -> list[AnalysisResult]:
    clips = data.get("clips")
    if clips is None:
        single = _analysis_from_mimo_dict(data, artist=artist, model=model)
        return [single] if single.judge_status == "keep" else []
    if not isinstance(clips, list):
        return [
            _failed_result(
                artist,
                "MiMo response clips must be an array",
                model=model,
            )
        ]

    results: list[AnalysisResult] = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            results.append(
                _failed_result(
                    artist,
                    f"MiMo clip #{index} must be an object",
                    model=model,
                )
            )
            continue
        result = _analysis_from_mimo_dict(clip, artist=artist, model=model)
        if result.judge_status == "keep":
            result.clip_type = str(clip.get("clip_type") or "").strip()
            result.topic_summary = str(clip.get("topic_summary") or "").strip()
            result.why_viewer_would_watch = str(
                clip.get("why_viewer_would_watch") or ""
            ).strip()
            result.completeness_score = _bounded_float(
                clip.get("completeness_score"),
                default=0.0,
            )
            result.confidence = _bounded_float(clip.get("confidence"), default=0.0)
            results.append(result)
    return results


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    return {}


def _failed_result(artist: str, reason: str, *, model: str) -> AnalysisResult:
    return AnalysisResult(
        title=f"{artist} candidate",
        description="Pending manual review",
        tags=["live"],
        quality_score=0.0,
        retain_recommendation=False,
        quality_reason=str(reason),
        judge_status="judge_failed",
        judge_error=str(reason),
        model_name=model,
    )
