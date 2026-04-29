# src/autoslice/mllm_sdk/visual_analyzer.py
# Copyright (c) 2024 bilive.
# 多模型协作架构 - 视觉分析模块

import base64
import os
import subprocess
import tempfile
from typing import List, Dict, Any
from openai import OpenAI
from src.log.logger import scan_log

VISUAL_ANALYSIS_PROMPT = """分析这些从直播视频提取的关键帧图片，提供以下信息（以 JSON 格式返回）：

1. visual_title: 基于画面内容的简短标题建议（不超过20字）
2. visual_description: 画面内容描述（50字左右）
3. visual_tags: 3-5个视觉相关标签（如游戏类型、场景、活动等）
4. visual_quality: 画面质量评分（0-1），评估画面是否精彩、有吸引力
5. visual_highlights: 画面中的精彩元素或亮点
6. content_type: 内容类型，选择其一：gameplay/chat/singing/dance/other

主播名：{artist}
"""


def extract_key_frames(video_path: str, fps: float = 0.5) -> List[str]:
    """从视频提取关键帧图片

    Args:
        video_path: 视频文件路径
        fps: 提取频率，0.5表示每2秒提取1帧

    Returns:
        List[str]: 提取的帧图片路径列表
    """
    temp_dir = tempfile.mkdtemp(prefix="bilive_frames_")
    output_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"fps={fps}",
            "-q:v", "2",
            output_pattern
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        frames = sorted([
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir)
            if f.endswith(".jpg")
        ])

        scan_log.info(f"Extracted {len(frames)} frames from {video_path} at {fps} fps")
        return frames

    except subprocess.CalledProcessError as e:
        scan_log.error(f"ffmpeg frame extraction failed: {e.stderr.decode()}")
        return []
    except FileNotFoundError:
        scan_log.error("ffmpeg not found, please install ffmpeg")
        return []


def encode_image_base64(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze_frames(
    frames: List[str],
    artist: str,
    model_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
    prompt: str = None
) -> Dict[str, Any]:
    """使用 GGUF 模型分析关键帧图片

    Args:
        frames: 帧图片路径列表
        artist: 主播名称
        model_url: LM Studio 服务地址
        model_name: 模型名称
        prompt: 自定义分析 prompt

    Returns:
        Dict: 视觉分析结果
    """
    if not frames:
        scan_log.warning("No frames to analyze")
        return {"visual_quality": 0.0, "error": "no_frames"}

    analysis_prompt = prompt or VISUAL_ANALYSIS_PROMPT
    analysis_prompt = analysis_prompt.replace("{artist}", artist)

    client = OpenAI(base_url=model_url, api_key="lm-studio")

    # 限制帧数量，避免请求过大
    max_frames = min(len(frames), 5)
    selected_frames = frames[:max_frames]

    # 构建消息内容
    content = []
    for frame_path in selected_frames:
        base64_image = encode_image_base64(frame_path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        })
    content.append({
        "type": "text",
        "text": analysis_prompt
    })

    scan_log.info(f"Analyzing {len(selected_frames)} frames with model at {model_url}")

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的直播画面分析师。请严格按照 JSON 格式返回结果。"
                },
                {
                    "role": "user",
                    "content": content
                }
            ],
            temperature=0.7,
            max_tokens=500
        )

        result_text = completion.choices[0].message.content
        scan_log.info(f"Visual analysis response: {result_text[:200]}...")

        # 尝试解析 JSON
        import json
        try:
            result = json.loads(result_text)
            return result
        except json.JSONDecodeError:
            scan_log.warning(f"Failed to parse JSON, returning raw text")
            return {"raw_response": result_text, "visual_quality": 0.5}

    except Exception as e:
        scan_log.error(f"Visual analysis API call failed: {e}")
        return {"visual_quality": 0.0, "error": str(e)}


def cleanup_frames(frames: List[str]) -> None:
    """清理临时帧图片文件"""
    if frames:
        temp_dir = os.path.dirname(frames[0])
        for frame in frames:
            try:
                os.remove(frame)
            except OSError:
                pass
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass
        scan_log.info(f"Cleaned up {len(frames)} temporary frame files")