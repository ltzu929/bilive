# src/autoslice/mllm_sdk/multi_modal_analyzer.py
# Copyright (c) 2024 bilive.
# 多模型协作架构 - 综合分析模块

import json
from typing import Dict, Any
from src.log.logger import scan_log
from src.autoslice.analysis_result import AnalysisResult, Highlight, TrimSuggestion
from .visual_analyzer import extract_key_frames, analyze_frames, cleanup_frames
from .audio_analyzer import analyze_audio


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


def combine_analysis(
    visual_result: Dict[str, Any],
    audio_result: Dict[str, Any],
    artist: str
) -> Dict[str, Any]:
    """综合视觉和音频分析结果

    Args:
        visual_result: 视觉分析结果（可能为空）
        audio_result: 音频分析结果
        artist: 主播名称

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

    # 综合质量评分
    # 纯音频模式：audio_quality * 1.0
    # 多模态模式：(visual_quality * 0.6 + audio_quality * 0.4)
    if visual_quality > 0:
        quality_score = (visual_quality * 0.6 + audio_quality * 0.4)
    else:
        quality_score = audio_quality

    # 综合标题
    if visual_title:
        title = visual_title
    elif transcript and len(transcript) > 20:
        # 从转录文本生成标题（取精彩片段）
        title = f"{artist}直播-{transcript[:25]}"
    else:
        title = f"{artist}精彩片段"

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

    # 保留建议
    retain_recommendation = quality_score >= 0.5

    quality_reason = f"音频评分:{audio_quality:.1f}"
    if visual_quality > 0:
        quality_reason = f"视觉评分:{visual_quality:.1f}, 音频评分:{audio_quality:.1f}"
    if audio_emotion != "neutral":
        quality_reason += f", 情绪:{audio_emotion}"

    return {
        "title": title,
        "description": transcript[:100] if transcript else "精彩直播片段",
        "tags": tags,
        "content_type": content_type,
        "quality_score": quality_score,
        "retain_recommendation": retain_recommendation,
        "quality_reason": quality_reason,
        "highlights": [],
        "emotion_peak_time": 0.0,
        "suggested_trim": None
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
    emotion_model: str = "facebook/wav2vec2-base-robust-emotion"
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
            emotion_model=emotion_model
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
    scan_log.info("Combining analysis results...")
    combined = combine_analysis(visual_result, audio_result, artist)

    # 4. 构建 AnalysisResult
    result = AnalysisResult.from_dict(combined)

    scan_log.info(
        f"Multi-modal analysis complete: title={result.title}, "
        f"quality={result.quality_score:.2f}, retain={result.retain_recommendation}"
    )

    return result