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
    MIMO_ENCODE_PARALLELISM,
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


class MimoClipResults(list):
    def __init__(
        self,
        items=(),
        *,
        empty_reason: str = "",
        raw_response_summary: str = "",
        raw_response: dict[str, Any] | None = None,
    ):
        super().__init__(items)
        self.empty_reason = empty_reason
        self.raw_response_summary = raw_response_summary
        self.raw_response = dict(raw_response or {})


@dataclass
class EncodedMimoVideo:
    url: str
    base64_bytes: int


_status_lock = threading.Lock()
_encode_semaphore = threading.BoundedSemaphore(max(1, MIMO_ENCODE_PARALLELISM))
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

    with _encode_semaphore:
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


def judge_candidate_clips_with_mimo(
    *,
    video_path: str,
    artist: str,
    danmaku_text: str,
    candidate_duration: float,
    candidate_start: float = 0.0,
    candidate_core_start: float | None = None,
    candidate_core_end: float | None = None,
    single_clip: bool = False,
    model: str = MIMO_MODEL,
    base_url: str = MIMO_BASE_URL,
    fps: float = MIMO_FPS,
    media_resolution: str = MIMO_MEDIA_RESOLUTION,
    timeout: float = MIMO_TIMEOUT,
    max_base64_bytes: int = MIMO_MAX_BASE64_BYTES,
    client_factory=OpenAI,
    encoder: Callable[..., EncodedMimoVideo] = encode_video_for_mimo,
) -> list[AnalysisResult]:
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        reason = "MIMO_API_KEY is not set"
        _set_status("error", error=reason)
        return [_failed_result(artist, reason, model=model)]

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
                        "你是直播聊天切片的短视频剪辑师和严格主编。"
                        "根据视频、音频、弹幕和时间关系，返回严格 JSON。"
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
                                candidate_start=candidate_start,
                                core_start=candidate_core_start,
                                core_end=candidate_core_end,
                            ),
                        },
                    ],
                },
            ],
            max_completion_tokens=2048,
            timeout=timeout,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception as exc:
        reason = f"MiMo failed: {exc}"
        _set_status("error", error=reason)
        scan_log.warning(reason)
        return [_failed_result(artist, reason, model=model)]

    try:
        if not completion.choices:
            raise ValueError("MiMo response did not include any choices")
        message = completion.choices[0].message
        parsed = _extract_json(str(getattr(message, "content", "") or ""))
        if parsed is None:
            raise ValueError("MiMo JSON parse failed")
        results = _analysis_list_from_mimo_dict(parsed, artist=artist, model=model)
        usage = _usage_to_dict(getattr(completion, "usage", None))
        response_model = str(getattr(completion, "model", model) or model)
        for result in results:
            result.token_usage = usage
            result.model_name = response_model
            if single_clip and len(results) > 1:
                results = MimoClipResults(
                    [_select_primary_clip(results)],
                    empty_reason=getattr(results, "empty_reason", ""),
                    raw_response_summary=getattr(results, "raw_response_summary", ""),
                    raw_response=getattr(results, "raw_response", {}),
                )
    except Exception as exc:
        reason = f"MiMo response failed: {exc}"
        _set_status("error", error=reason)
        return [_failed_result(artist, reason, model=model)]

    failed = next((item for item in results if item.judge_status == "judge_failed"), None)
    if failed is not None:
        _set_status("error", error=failed.judge_error or failed.quality_reason)
    else:
        _set_status("idle")
    return results


def _empty_reason_from_response(data: dict[str, Any]) -> str:
    for key in ("empty_reason", "reason", "observed_issue", "summary"):
        value = _compact_response_value(data.get(key))
        if value:
            return value
    return "MiMo returned empty clips"


def _summarize_empty_response(data: dict[str, Any]) -> str:
    parts = []
    for key in ("empty_reason", "reason", "observed_issue", "summary"):
        value = _compact_response_value(data.get(key))
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def _compact_response_value(value: Any, *, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    compact = " ".join(value.split())
    if len(compact) > limit:
        return compact[: limit - 3] + "..."
    return compact


def judge_candidate_with_mimo(
    *,
    video_path: str,
    artist: str,
    danmaku_text: str,
    candidate_duration: float,
    candidate_start: float = 0.0,
    candidate_core_start: float | None = None,
    candidate_core_end: float | None = None,
    model: str = MIMO_MODEL,
    base_url: str = MIMO_BASE_URL,
    fps: float = MIMO_FPS,
    media_resolution: str = MIMO_MEDIA_RESOLUTION,
    timeout: float = MIMO_TIMEOUT,
    max_base64_bytes: int = MIMO_MAX_BASE64_BYTES,
    client_factory=OpenAI,
    encoder: Callable[..., EncodedMimoVideo] = encode_video_for_mimo,
) -> AnalysisResult:
    results = judge_candidate_clips_with_mimo(
        video_path=video_path,
        artist=artist,
        danmaku_text=danmaku_text,
        candidate_duration=candidate_duration,
        candidate_start=candidate_start,
        candidate_core_start=candidate_core_start,
        candidate_core_end=candidate_core_end,
        model=model,
        base_url=base_url,
        fps=fps,
        media_resolution=media_resolution,
        timeout=timeout,
        max_base64_bytes=max_base64_bytes,
        client_factory=client_factory,
        encoder=encoder,
    )
    if not results:
        return AnalysisResult(
            title=f"{artist} candidate",
            description="Pending manual review",
            tags=["live"],
            retain_recommendation=False,
            quality_reason="MiMo found no postable chat clips",
            judge_status="drop",
            model_name=model,
        )
    return results[0]

def _build_prompt(
    *,
    artist: str,
    danmaku_text: str,
    candidate_duration: float,
    candidate_start: float = 0.0,
    core_start: float | None = None,
    core_end: float | None = None,
) -> str:
    core_text = (
        f"{float(core_start):.3f}-{float(core_end):.3f}s"
        if core_start is not None and core_end is not None
        else "(not available)"
    )
    return (
        "候选元数据:\n"
        f"- 主播: {artist or 'unknown'}\n"
        f"- 候选时长秒数: {float(candidate_duration or 0):.3f}\n"
        f"- 候选在原视频中的起点秒数: {float(candidate_start or 0):.3f}\n"
        f"- 弹幕检测到的爆点核心（相对候选）: {core_text}\n"
        f"- 候选范围内弹幕: {str(danmaku_text or '').strip() or '(none)'}\n\n"
        "你的角色:\n"
        "你是短视频剪辑师 + 严格主编。你的目标不是多产出切片，"
        "而是避免发布低质量聊天切片。弹幕峰值只是候选来源，不是保留理由。\n\n"
        "任务:\n"
        "在这个最多约 5 分钟的直播聊天候选里，找出 0 个或 1 个"
        "可以独立投稿的聊天短片。故事、观点、情绪反应、弹幕互动没有固定"
        "优先级；选择最能独立成片、最容易被陌生观众理解、最有观看价值的片段。\n\n"
        "每个保留片段必须:\n"
        "- 有明确主题，能被一句具体标题概括。\n"
        "- 陌生观众不看原直播上下文也能理解。\n"
        "- 有清楚开头、发展和落点。这是硬性要求：\n"
        "    1. 开头必须是一个完整句子或话题的起点，不能从半句话中间切入；\n"
        "    2. 中间要有清晰的铺垫或发展；\n"
        "    3. 结尾必须落在一个完整的落点/收尾上（梗抖响、观点说完、情绪释放"
        "或互动收束），不能在半句话中间戛然而止。\n"
        "- 至少具备一种观看价值: 完整梗或故事、明确观点、强情绪反应、弹幕互动。\n"
        "- 标题采用 B 站口语标题，轻微整活但不夸张，不能写泛泛的直播精彩片段。\n\n"
        "关于 trim_start/trim_end 的硬性要求:\n"
        "- trim_start 必须对齐到一句完整话的开头，trim_end 必须对齐到一句完整话"
        "说完之后，务必让片段首尾都是完整句子，宁可多留一点也不要切掉半句。\n"
        "- 参考弹幕时间轴 [mm:ss] 判断爆点真正发生的时刻与前因后果，不要盲目"
        "以候选正中间为爆点。\n\n"
        "返回 JSON object，顶层必须包含 clips。clips 是数组。"
        "如果没有达标片段，返回 {\"clips\": []}。每个 clips 元素必须包含:"
        "If clips is empty, include top-level empty_reason with a brief rejection reason.\n"
        " decision, clip_type, topic_summary, why_viewer_would_watch, reason, "
        "title, description, tags, quality_score, completeness_score, confidence, "
        "trim_start, trim_end, core_start, core_end。decision 只能是 keep。"
        "quality_score、completeness_score、confidence 必须是 0.0 到 1.0 之间的数字，"
        "不是百分制数字，也不能填写文字。"
        "trim_start/trim_end 是相对"
        "候选视频开头的秒数。tags 是字符串数组。\n"
        "本次候选窗口只允许返回一个主片段；如果有多个可能片段，只保留最完整、"
        "最有爆点的一个。keep 时还必须返回 core_start 和 core_end，表示片段内"
        "真正的爆点核心区间（相对候选开头的秒数）。最终 trim 必须覆盖该核心，"
        "并同时覆盖核心之前的铺垫和核心之后的落点；无法证明完整事件时返回"
        "{\"clips\": []}，并填写 empty_reason。"
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

    quality_score, quality_issue = _strict_score(data, "quality_score")
    completeness_score = 0.0
    confidence = 0.0
    score_issues = [quality_issue] if quality_issue else []
    if retain:
        completeness_score, completeness_issue = _strict_score(
            data,
            "completeness_score",
        )
        confidence, confidence_issue = _strict_score(data, "confidence")
        score_issues.extend(
            issue
            for issue in (completeness_issue, confidence_issue)
            if issue
        )
    elif quality_issue:
        return _failed_result(artist, quality_issue, model=model)

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

    core_start = None
    core_end = None
    if retain and ("core_start" in data or "core_end" in data):
        try:
            core_start = float(data.get("core_start"))
            core_end = float(data.get("core_end"))
            if not math.isfinite(core_start) or not math.isfinite(core_end):
                raise ValueError
        except (TypeError, ValueError):
            return _failed_result(
                artist,
                "MiMo keep response core_start/core_end must be finite numbers",
                model=model,
            )

    result = AnalysisResult(
        title=title_value.strip(),
        description=description_value.strip(),
        tags=[tag.strip() for tag in tags if tag.strip()],
        retain_recommendation=retain,
        quality_reason=reason,
        quality_score=quality_score,
        judge_status="keep" if retain else "drop",
        judge_error="",
        suggested_trim=trim,
        core_start=core_start,
        core_end=core_end,
        model_name=model,
        completeness_score=completeness_score,
        confidence=confidence,
    )
    if retain and score_issues:
        review_reason = (
            "Automatic publish quality gate requires review: "
            + ", ".join(score_issues)
        )
        result.judge_status = "review"
        result.retain_recommendation = False
        result.judge_error = review_reason
        result.quality_reason = f"{reason}; {review_reason}"
    return result


def _analysis_list_from_mimo_dict(
    data: dict[str, Any],
    *,
    artist: str,
    model: str,
) -> list[AnalysisResult]:
    clips = data.get("clips")
    if clips is None:
        single = _analysis_from_mimo_dict(data, artist=artist, model=model)
        single.raw_model_response = dict(data)
        if single.judge_status in {"keep", "review"}:
            return MimoClipResults([single], raw_response=data)
        if single.judge_status == "judge_failed":
            return MimoClipResults([single], raw_response=data)
        return MimoClipResults(
            empty_reason=single.quality_reason,
            raw_response_summary=_summarize_empty_response(data),
            raw_response=data,
        )
    if not isinstance(clips, list):
        result = _failed_result(
            artist,
            "MiMo response clips must be an array",
            model=model,
        )
        result.raw_model_response = dict(data)
        return [result]
    if not clips:
        return MimoClipResults(
            empty_reason=_empty_reason_from_response(data),
            raw_response_summary=_summarize_empty_response(data),
            raw_response=data,
        )

    results: list[AnalysisResult] = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            result = _failed_result(
                artist,
                f"MiMo clip #{index} must be an object",
                model=model,
            )
            result.raw_model_response = dict(data)
            results.append(result)
            continue
        result = _analysis_from_mimo_dict(clip, artist=artist, model=model)
        result.raw_model_response = dict(data)
        if result.judge_status in {"keep", "review"}:
            result.clip_type = str(clip.get("clip_type") or "").strip()
            result.topic_summary = str(clip.get("topic_summary") or "").strip()
            result.why_viewer_would_watch = str(
                clip.get("why_viewer_would_watch") or ""
            ).strip()
            results.append(result)
        elif result.judge_status == "judge_failed":
            results.append(result)
    return MimoClipResults(results, raw_response=data)


def _select_primary_clip(results: list[AnalysisResult]) -> AnalysisResult:
    """Select one deterministic primary clip for a candidate window."""
    def rank(result: AnalysisResult) -> tuple[float, ...]:
        def number(value: Any) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return 0.0
            return parsed if math.isfinite(parsed) else 0.0

        core_duration = 0.0
        if result.core_start is not None and result.core_end is not None:
            core_duration = max(
                0.0,
                number(result.core_end) - number(result.core_start),
            )
        return (
            1.0 if result.judge_status == "keep" else 0.0,
            number(result.quality_score),
            number(result.completeness_score),
            number(result.confidence),
            core_duration,
        )

    return max(enumerate(results), key=lambda item: (rank(item[1]), -item[0]))[1]


def _strict_score(data: dict[str, Any], field: str) -> tuple[float, str]:
    if field not in data or data.get(field) is None:
        return 0.0, f"{field}=missing"
    value = data.get(field)
    if isinstance(value, bool):
        return 0.0, f"{field}=invalid"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0, f"{field}=invalid"
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        return 0.0, f"{field}=out_of_range"
    return parsed, ""


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
