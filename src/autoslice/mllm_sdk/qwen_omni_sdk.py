# src/autoslice/mllm_sdk/qwen_omni_sdk.py
# Copyright (c) 2024 bilive.

import base64
import json
from openai import OpenAI
from src.log.logger import scan_log
from src.autoslice.analysis_result import AnalysisResult

# 默认分析 prompt
DEFAULT_ANALYSIS_PROMPT = """分析这个视频切片片段，提供以下信息（以 JSON 格式返回）：

1. title: 吸引人的切片标题（不超过30字）
2. description: 内容摘要（100字左右）
3. tags: 3-5个相关标签（数组格式）
4. content_type: 内容类型，选择其一：gameplay/chat/singing/dance/other
5. quality_score: 质量评分（0-1），评估这个切片的精彩程度
6. retain_recommendation: 是否值得保留（true/false）
7. quality_reason: 质量评估理由（简短说明）
8. highlights: 精彩时刻列表，每个包含 start/end/score/desc
9. emotion_peak_time: 情感高峰时间点（秒）
10. suggested_trim: 建议裁剪部分，包含 trim_start/trim_end/reason

主播名：{artist}
"""


def encode_video_base64(video_path: str) -> str:
    """将视频文件编码为 base64"""
    with open(video_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def qwen_omni_analyze(video_path: str, artist: str, api_key: str = None, prompt: str = None) -> AnalysisResult:
    """使用 QWEN OMNI 分析视频切片

    Args:
        video_path: 视频文件路径
        artist: 主播名称
        api_key: DashScope API Key（可选，默认从配置读取）
        prompt: 自定义分析 prompt（可选）

    Returns:
        AnalysisResult: 分析结果对象，失败返回 None
    """
    from src.config import QWEN_API_KEY, SLICE_PROMPT

    # API Key 优先使用传入参数，否则使用配置（与现有 qwen 共用）
    if api_key is None:
        api_key = QWEN_API_KEY

    if not api_key:
        scan_log.error("QWEN OMNI API Key not configured")
        return None

    # Prompt 优先使用自定义，否则使用默认
    analysis_prompt = prompt or SLICE_PROMPT or DEFAULT_ANALYSIS_PROMPT
    analysis_prompt = analysis_prompt.replace("{artist}", artist)

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    base64_video = encode_video_base64(video_path)

    scan_log.info(f"Calling QWEN OMNI for video: {video_path}")

    try:
        completion = client.chat.completions.create(
            model="qwen2.5-omni-7b-instruct",  # 模型名称，待确认后可调整
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的直播视频分析师，擅长多模态内容分析。请严格按照 JSON 格式返回结果。"
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": f"data:video/mp4;base64,{base64_video}"}
                        },
                        {
                            "type": "text",
                            "text": analysis_prompt
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"}
        )

        result_json = completion.choices[0].message.content
        scan_log.info(f"OMNI raw response: {result_json}")

        result = AnalysisResult.from_json(result_json)
        if result is None:
            scan_log.error("Failed to parse OMNI response as AnalysisResult")
            return None

        scan_log.info(f"OMNI analysis complete: title={result.title}, quality={result.quality_score}")

        return result

    except Exception as e:
        scan_log.error(f"QWEN OMNI API call failed: {e}")
        return None