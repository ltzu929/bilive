# src/autoslice/mllm_sdk/multi_modal_analyzer.py
# Copyright (c) 2024 bilive.
# 多模型协作架构 - 综合分析模块

import json
import re
from typing import Dict, Any, Optional
from openai import OpenAI
from src.log.logger import scan_log
from src.autoslice.analysis_result import AnalysisResult, Highlight, TrimSuggestion
from .visual_analyzer import extract_key_frames, analyze_frames, cleanup_frames
from .audio_analyzer import analyze_audio
from .judge import judge_and_title, JudgeResult


COMBINE_ANALYSIS_PROMPT = """基于以下视觉和音频分析结果，综合生成直播切片的分析结果：

视觉分析：
{visual_result}

音频分析：
{audio_result}

请提供以下信息（以 JSON 格式返回）：
1. title: 综合视觉和音频内容的吸引人标题（不超过30字）
2. description: 内容摘要（100字左右）
3. tags: 3-5个综合标签
4. content_type: 内容类型，选择其一：gameplay/chat/singing/dance/other
5. quality_score: 综合质量评分（0-1）
6. retain_recommendation: 是否值得保留（true/false）
7. quality_reason: 质量评估理由
"""

# 默认配置
DEFAULT_VISUAL_MODEL_URL = "http://localhost:1234/v1"
DEFAULT_VISUAL_MODEL_NAME = "local-model"
DEFAULT_FRAME_FPS = 0.5
DEFAULT_WHISPER_MODEL = "base"


def _truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip("，。！？、,!?")


def _truncate_description(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text

    candidate = text[:max_len]
    sentence_breaks = [candidate.rfind(mark) for mark in "。！？!?"]
    break_at = max(sentence_breaks)
    if break_at >= max_len * 0.55:
        return candidate[:break_at + 1]

    return candidate.rstrip("，。！？、,!?") + "。"


def _build_audio_title(artist: str, keywords: list, transcript: str) -> str:
    """Build a conservative title without copying raw ASR noise verbatim."""
    clean_keywords = []
    for keyword in keywords:
        keyword = re.sub(r"\s+", "", str(keyword))
        if 2 <= len(keyword) <= 6 and keyword not in clean_keywords:
            clean_keywords.append(keyword)

    template = (
        "直播高能"
        if any(k in transcript for k in ("哈哈", "厉害", "牛逼", "太强", "666"))
        else "直播片段"
    )

    if clean_keywords:
        title = f"{artist}{template}：{'、'.join(clean_keywords[:2])}"
    elif transcript:
        snippet = re.sub(r"[，。！？、,!?嗯额然后就是那个]", "", transcript)[:12]
        title = f"{artist}{template}：{snippet}" if snippet else f"{artist}{template}"
    else:
        title = f"{artist}精彩片段"

    return _truncate_text(title, 30)


TITLE_PROMPT = """基于以下直播切片信息，生成标题和简介。

主播：{artist}
弹幕内容（观众反应）：{danmaku_text}
主播讲话（Whisper转录）：{transcript}

要求：
1. title: 吸引人的标题（不超过30字），体现这段切片的亮点
2. description: 内容简介（不超过100字），概括这段直播的主要内容

直接返回JSON格式，不要其他文字：
{{"title": "...", "description": "..."}}"""


def _llm_generate_title(
    artist: str,
    transcript: str,
    danmaku_text: str,
    model_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
    timeout: float = 120.0,
) -> Optional[Dict[str, str]]:
    """Call local LLM to generate title and description from danmaku + transcript.

    Returns dict with 'title' and 'description' keys, or None on failure.
    """
    prompt = TITLE_PROMPT.format(
        artist=artist,
        danmaku_text=danmaku_text or "(无弹幕)",
        transcript=transcript or "(无转录)",
    )
    try:
        client = OpenAI(base_url=model_url, api_key="lm-studio")
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        msg = completion.choices[0].message
        scan_log.info(f"LLM raw content={msg.content!r}")
        if hasattr(msg, "reasoning_content"):
            scan_log.info(f"LLM reasoning_content={msg.reasoning_content!r}")

        # Try content first, fall back to reasoning_content for Qwen 3.5+
        def _extract_json(text: str) -> Optional[Dict[str, str]]:
            if not text:
                return None
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            return None

        result = _extract_json(msg.content or "")
        if result is None:
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                scan_log.info("Falling back to reasoning_content for title generation")
                result = _extract_json(reasoning)
        return result
    except Exception as e:
        scan_log.warning(f"LLM title generation failed: {e}")
    return None


def combine_analysis(
    visual_result: Dict[str, Any],
    audio_result: Dict[str, Any],
    artist: str,
    danmaku_text: str = "",
    model_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
) -> Dict[str, Any]:
    """综合视觉和音频分析结果

    Args:
        visual_result: 视觉分析结果（可能为空）
        audio_result: 音频分析结果
        artist: 主播名称
        danmaku_text: 切片时段内的弹幕文本
        model_url: 本地 LLM 服务地址
        model_name: 本地 LLM 模型名称

    Returns:
        Dict: 综合分析结果
    """
    # 提取关键信息
    visual_quality = visual_result.get("visual_quality", 0.0) if visual_result else 0.0
    audio_quality = audio_result.get("audio_quality", 0.5)

    visual_title = visual_result.get("visual_title", "") if visual_result else ""
    visual_tags = visual_result.get("visual_tags", []) if visual_result else []
    visual_highlights = visual_result.get("visual_highlights", []) if visual_result else []

    audio_emotion = audio_result.get("emotion", "neutral")
    audio_keywords = audio_result.get("audio_keywords", [])
    transcript = audio_result.get("transcript", "")
    transcript_segments = audio_result.get("segments", [])

    # 综合质量评分
    # 纯音频模式：audio_quality * 1.0
    # 多模态模式：(visual_quality * 0.6 + audio_quality * 0.4)
    if visual_quality > 0:
        quality_score = (visual_quality * 0.6 + audio_quality * 0.4)
    else:
        quality_score = audio_quality

    # 综合标题：优先 LLM，降级视觉标题，最后模板
    title = ""
    description = ""

    if transcript or danmaku_text:
        llm_result = _llm_generate_title(
            artist, transcript, danmaku_text, model_url, model_name
        )
        if llm_result:
            title = llm_result.get("title", "")
            description = llm_result.get("description", "")
            scan_log.info(
                f"LLM title result: title={title!r}, description={description!r}"
            )
        else:
            scan_log.info("LLM title generation returned None, falling back to template")

    if not title:
        if visual_title:
            title = _truncate_text(visual_title, 30)
        else:
            title = _build_audio_title(artist, audio_keywords, transcript)

    if not description:
        description = _truncate_description(transcript, 100) if transcript else "精彩直播片段"

    # 综合标签
    tags = list(set(visual_tags + audio_keywords))[:5]
    if not tags:
        tags = ["直播", "精彩"]

    # 内容类型判断
    content_type = visual_result.get("content_type", "other") if visual_result else "other"
    if content_type == "other":
        # 从音频推断内容类型
        if audio_emotion in ["excited", "angry"]:
            content_type = "gameplay"
        elif "唱歌" in transcript or "sing" in transcript.lower():
            content_type = "singing"
        elif audio_emotion in ["happy", "calm"]:
            content_type = "chat"

    # 保留建议：高分直接保留，边界分数需要情绪信号支撑
    retain_recommendation = (
        quality_score >= 0.6
        or (quality_score >= 0.5 and audio_emotion in ("excited", "happy", "angry", "calm"))
    )

    quality_reason = f"音频评分:{audio_quality:.1f}"
    if visual_quality > 0:
        quality_reason = f"视觉评分:{visual_quality:.1f}, 音频评分:{audio_quality:.1f}"
    if audio_emotion != "neutral":
        quality_reason += f", 情绪:{audio_emotion}"

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "content_type": content_type,
        "quality_score": quality_score,
        "retain_recommendation": retain_recommendation,
        "quality_reason": quality_reason,
        "highlights": [],
        "emotion_peak_time": 0.0,
        "suggested_trim": None,
        "transcript": transcript,
        "transcript_segments": transcript_segments,
    }


def multi_modal_analyze(
    video_path: str,
    artist: str,
    visual_model_url: str = DEFAULT_VISUAL_MODEL_URL,
    visual_model_name: str = DEFAULT_VISUAL_MODEL_NAME,
    frame_fps: float = DEFAULT_FRAME_FPS,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    enable_visual: bool = True,
    enable_audio: bool = True,
    enable_emotion: bool = False,
    emotion_model: str = "facebook/wav2vec2-base-robust-emotion",
    danmaku_text: str = "",
    whisper_engine: str = "openai-whisper",
    whisper_device: str = "cpu",
) -> AnalysisResult:
    """多模型协作分析视频切片

    Args:
        video_path: 视频文件路径
        artist: 主播名称
        visual_model_url: LM Studio 服务地址
        visual_model_name: 模型名称
        frame_fps: 帧提取频率
        whisper_model: Whisper 模型大小
        enable_visual: 是否启用视觉分析
        enable_audio: 是否启用音频分析
        danmaku_text: 切片时段内的弹幕文本

    Returns:
        AnalysisResult: 综合分析结果
    """
    scan_log.info(f"Starting multi-modal analysis for: {video_path}")

    visual_result = {}
    audio_result = {}
    frames = []

    # 1. 音频分析
    if enable_audio:
        scan_log.info("Running audio analysis...")
        audio_result = analyze_audio(
            video_path,
            whisper_model,
            enable_emotion=enable_emotion,
            emotion_model=emotion_model,
            whisper_engine=whisper_engine,
            whisper_device=whisper_device,
        )

        # 释放 GPU 显存（Whisper 和情感模型）
        if enable_emotion:
            from .audio_analyzer import unload_emotion_model
            unload_emotion_model()
    else:
        audio_result = {"transcript": "", "emotion": "neutral"}

    # 2. 视觉分析（可选）
    if enable_visual:
        scan_log.info("Running visual analysis...")
        frames = extract_key_frames(video_path, frame_fps)
        if frames:
            visual_result = analyze_frames(
                frames, artist, visual_model_url, visual_model_name
            )
            # 清理临时帧文件
            cleanup_frames(frames)
        else:
            scan_log.warning("No frames extracted, skipping visual analysis")
            visual_result = {"visual_quality": 0.3, "error": "no_frames"}

    # 3. 综合分析
    if enable_visual:
        # 多模态模式：使用 combine_analysis 综合视觉+音频
        scan_log.info("Combining analysis results (multi-modal)...")
        combined = combine_analysis(
            visual_result, audio_result, artist,
            danmaku_text=danmaku_text,
            model_url=visual_model_url,
            model_name=visual_model_name,
        )
        result = AnalysisResult.from_dict(combined)
    else:
        # local-audio 模式：使用 LLM judge 直接判断保留+生成标题
        scan_log.info("Running LLM judge for retain/title decision...")
        transcript = audio_result.get("transcript", "") if audio_result else ""
        judge_result = judge_and_title(
            artist=artist,
            danmaku_text=danmaku_text,
            transcript=transcript,
            model_url=visual_model_url,
            model_name=visual_model_name,
        )
        result = judge_result.to_analysis_result()
        # 补充转录信息
        result.transcript = transcript
        segments = audio_result.get("segments", []) if audio_result else []
        from src.autoslice.analysis_result import TranscriptSegment
        result.transcript_segments = [
            TranscriptSegment(start=s.get("start", 0), end=s.get("end", 0), text=s.get("text", ""))
            for s in segments
        ]

    scan_log.info(
        f"Multi-modal analysis complete: title={result.title}, "
        f"quality={result.quality_score:.2f}, retain={result.retain_recommendation}"
    )

    return result
