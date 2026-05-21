# src/autoslice/mllm_sdk/judge.py
# Copyright (c) 2024 bilive.
# LLM 质量判断 + 标题生成（替代启发式评分）

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from openai import OpenAI
from src.log.logger import scan_log


@dataclass
class JudgeResult:
    """LLM 判断结果"""
    retain: bool = True
    retain_reason: str = ""
    title: str = ""
    description: str = ""
    content_type: str = "other"
    quality_score: float = 0.5
    # 保持与 AnalysisResult 兼容的字段
    tags: list = field(default_factory=list)
    highlights: list = field(default_factory=list)
    emotion_peak_time: float = 0.0
    suggested_trim: Optional[Any] = None
    transcript: str = ""
    transcript_segments: list = field(default_factory=list)

    def to_analysis_result(self):
        """转换为 AnalysisResult 兼容对象"""
        from src.autoslice.analysis_result import AnalysisResult, Highlight, TrimSuggestion
        return AnalysisResult(
            title=self.title,
            description=self.description,
            tags=self.tags,
            content_type=self.content_type,
            quality_score=self.quality_score,
            retain_recommendation=self.retain,
            quality_reason=self.retain_reason,
            highlights=[Highlight(h.get("start", 0), h.get("end", 0), h.get("score", 0), h.get("desc")) for h in self.highlights if isinstance(h, dict)],
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
  "content_type": "gameplay/chat/singing/dance/other"
}}

判断标准：
- retain=true: 内容有看点，观众互动热烈，主播有精彩表现
- retain=false: 内容平淡，无实质内容，纯沉默期，只有无意义重复

直接返回 JSON，不要其他文字。"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 回复中提取 JSON"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None


def judge_and_title(
    artist: str,
    danmaku_text: str = "",
    transcript: str = "",
    model_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
    timeout: float = 120.0,
) -> JudgeResult:
    """LLM 单次调用：判断是否保留 + 生成标题

    Args:
        artist: 主播名
        danmaku_text: 切片区间弹幕文本
        transcript: Whisper 转录文本
        model_url: LM Studio 服务地址
        model_name: 模型名称
        timeout: 超时秒数

    Returns:
        JudgeResult 包含 retain/title/description/content_type
    """
    prompt = SLICE_JUDGE_PROMPT.format(
        artist=artist,
        danmaku_text=danmaku_text or "(无弹幕)",
        transcript=transcript or "(无转录)",
    )

    # 截断超长内容，避免超出 context window
    if len(danmaku_text) > 800:
        danmaku_text = danmaku_text[-800:]
    if len(transcript) > 1500:
        transcript = transcript[-1500:]

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

        # 尝试从 content 提取 JSON
        result = _extract_json(msg.content or "")
        if result is None:
            # Qwen 3.5+ 推理模型：推理写在 reasoning_content，答案在 content
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                scan_log.info("Falling back to reasoning_content for judge result")
                result = _extract_json(reasoning)

        if result is not None:
            return JudgeResult(
                retain=bool(result.get("retain", True)),
                retain_reason=str(result.get("retain_reason", "")),
                title=str(result.get("title", "")),
                description=str(result.get("description", "")),
                content_type=str(result.get("content_type", "other")),
                quality_score=0.7 if result.get("retain", True) else 0.3,
                tags=result.get("tags", []),
            )

        scan_log.warning("Failed to parse judge JSON from LLM response")
        # JSON 解析失败 → fallback
        return JudgeResult(
            retain=True,
            retain_reason="LLM JSON parse failed, keeping by default",
            title=f"{artist}精彩片段",
            description="精彩直播片段",
            content_type="other",
            quality_score=0.5,
        )

    except Exception as e:
        scan_log.error(f"Judge LLM call failed: {e}")
        # LLM 调用失败 → fallback 模板标题 + 默认保留
        return JudgeResult(
            retain=True,
            retain_reason=f"LLM failed: {e}, keeping by default",
            title=f"{artist}精彩片段",
            description="精彩直播片段",
            content_type="other",
            quality_score=0.5,
        )