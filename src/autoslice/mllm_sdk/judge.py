# src/autoslice/mllm_sdk/judge.py
# Copyright (c) 2024 bilive.

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from openai import OpenAI
from src.log.logger import scan_log


@dataclass
class JudgeResult:
    """LLM judge result."""

    retain: bool = True
    retain_reason: str = ""
    title: str = ""
    description: str = ""
    content_type: str = "other"
    quality_score: float = 0.5
    tags: list = field(default_factory=list)
    highlights: list = field(default_factory=list)
    emotion_peak_time: float = 0.0
    suggested_trim: Optional[Any] = None
    transcript: str = ""
    transcript_segments: list = field(default_factory=list)

    def to_analysis_result(self):
        from src.autoslice.analysis_result import AnalysisResult, Highlight

        return AnalysisResult(
            title=self.title,
            description=self.description,
            tags=self.tags,
            content_type=self.content_type,
            quality_score=self.quality_score,
            retain_recommendation=self.retain,
            quality_reason=self.retain_reason,
            highlights=[
                Highlight(
                    h.get("start", 0),
                    h.get("end", 0),
                    h.get("score", 0),
                    h.get("desc"),
                )
                for h in self.highlights
                if isinstance(h, dict)
            ],
            emotion_peak_time=self.emotion_peak_time,
            suggested_trim=None,
            transcript=self.transcript,
            transcript_segments=self.transcript_segments,
        )


SLICE_JUDGE_PROMPT = """你是一个直播切片审核员。以下是一段直播切片的信息：
主播：{artist}
弹幕内容（观众反应）：{danmaku_text}
主播讲话（转录）：{transcript}

请判断这段切片是否值得上传，并生成标题。以 JSON 格式返回：
{{
  "retain": true/false,
  "retain_reason": "简短理由",
  "title": "不超过30字的吸引人标题",
  "description": "100字以内的内容摘要",
  "content_type": "gameplay/chat/singing/dance/other",
  "tags": ["标签1", "标签2"]
}}

判断标准：
- retain=true: 内容有看点，观众互动热烈，主播有精彩表现
- retain=false: 内容平淡，无实质内容，纯沉默，只有无意义重复

直接返回 JSON，不要返回其他文字。"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            return None
    return None


def _fallback_result(artist: str, reason: str) -> JudgeResult:
    return JudgeResult(
        retain=True,
        retain_reason=reason,
        title=f"{artist}精彩片段",
        description="精彩直播片段",
        content_type="other",
        quality_score=0.5,
    )


def _judge_result_from_dict(result: Dict[str, Any]) -> JudgeResult:
    retain = bool(result.get("retain", True))
    try:
        quality_score = float(result.get("quality_score", 0.7 if retain else 0.3))
    except (TypeError, ValueError):
        quality_score = 0.7 if retain else 0.3

    return JudgeResult(
        retain=retain,
        retain_reason=str(result.get("retain_reason", "")),
        title=str(result.get("title", "")),
        description=str(result.get("description", "")),
        content_type=str(result.get("content_type", "other")),
        quality_score=quality_score,
        tags=result.get("tags", []),
        highlights=result.get("highlights", []),
    )


def _trim_inputs(danmaku_text: str, transcript: str) -> tuple[str, str]:
    if len(danmaku_text) > 800:
        danmaku_text = danmaku_text[-800:]
    if len(transcript) > 1500:
        transcript = transcript[-1500:]
    return danmaku_text, transcript


def _build_judge_prompt(artist: str, danmaku_text: str, transcript: str) -> str:
    danmaku_text, transcript = _trim_inputs(danmaku_text, transcript)
    return SLICE_JUDGE_PROMPT.format(
        artist=artist,
        danmaku_text=danmaku_text or "(无弹幕)",
        transcript=transcript or "(无转录)",
    )


def _normalize_command(command: Any) -> list[str]:
    if isinstance(command, (list, tuple)):
        return [str(part) for part in command if str(part)]
    if isinstance(command, str) and command.strip():
        return shlex.split(command, posix=(os.name != "nt"))
    return []


def judge_and_title_local_subprocess(
    command: Any,
    artist: str,
    danmaku_text: str = "",
    transcript: str = "",
    timeout: float = 120.0,
) -> JudgeResult:
    """Run one local model process and parse a judge/title JSON response.

    stdin protocol:
    {
      "task": "judge_title",
      "artist": "...",
      "danmaku_text": "...",
      "transcript": "...",
      "prompt": "..."
    }

    The process should write a JSON object to stdout. Because the process exits
    after each call, model memory is released by the OS.
    """
    command_args = _normalize_command(command)
    if not command_args:
        return _fallback_result(artist, "local subprocess not configured")

    trimmed_danmaku, trimmed_transcript = _trim_inputs(danmaku_text, transcript)
    payload = {
        "task": "judge_title",
        "artist": artist,
        "danmaku_text": trimmed_danmaku,
        "transcript": trimmed_transcript,
        "prompt": _build_judge_prompt(artist, trimmed_danmaku, trimmed_transcript),
    }

    try:
        completed = subprocess.run(
            command_args,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as e:
        scan_log.error(f"Local LLM subprocess failed: {e}")
        return _fallback_result(artist, f"local subprocess failed: {e}")

    if completed.stderr:
        scan_log.info(f"Local LLM stderr: {completed.stderr.strip()}")
    if completed.returncode != 0:
        return _fallback_result(
            artist,
            f"local subprocess exited with code {completed.returncode}",
        )

    result = _extract_json(completed.stdout or "")
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        result = result["result"]
    if result is None:
        return _fallback_result(artist, "local subprocess JSON parse failed")

    return _judge_result_from_dict(result)


def _load_judge_provider_config() -> tuple[str, Any, float]:
    try:
        from src.config import (
            LLM_JUDGE_PROVIDER,
            LOCAL_LLM_COMMAND,
            LOCAL_LLM_TIMEOUT,
        )

        return LLM_JUDGE_PROVIDER, LOCAL_LLM_COMMAND, float(LOCAL_LLM_TIMEOUT)
    except Exception:
        return "openai-compatible", [], 120.0


def judge_and_title(
    artist: str,
    danmaku_text: str = "",
    transcript: str = "",
    model_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
    timeout: float = 120.0,
) -> JudgeResult:
    """Judge whether to retain a clip and generate title/description."""
    provider, local_command, local_timeout = _load_judge_provider_config()
    if provider == "local-subprocess":
        return judge_and_title_local_subprocess(
            local_command,
            artist=artist,
            danmaku_text=danmaku_text,
            transcript=transcript,
            timeout=local_timeout or timeout,
        )

    prompt = _build_judge_prompt(artist, danmaku_text, transcript)

    try:
        client = OpenAI(base_url=model_url, api_key="lm-studio")
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            timeout=timeout,
        )
        msg = completion.choices[0].message
        scan_log.info(f"Judge LLM raw content: {msg.content!r}")

        result = _extract_json(msg.content or "")
        if result is None:
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                scan_log.info("Falling back to reasoning_content for judge result")
                result = _extract_json(reasoning)

        if result is not None:
            return _judge_result_from_dict(result)

        scan_log.warning("Failed to parse judge JSON from LLM response")
        return _fallback_result(artist, "LLM JSON parse failed, keeping by default")

    except Exception as e:
        scan_log.error(f"Judge LLM call failed: {e}")
        return _fallback_result(artist, f"LLM failed: {e}, keeping by default")
