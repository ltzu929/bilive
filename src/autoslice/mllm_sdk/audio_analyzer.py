# src/autoslice/mllm_sdk/audio_analyzer.py
# Copyright (c) 2024 bilive.
# 多模型协作架构 - 音频分析模块

import os
import gc
import subprocess
import tempfile
from typing import Dict, Any, Optional
from src.log.logger import scan_log

# 全局变量缓存模型，避免重复加载
_emotion_model = None
_emotion_processor = None
_whisper_model = None

AUDIO_ANALYSIS_PROMPT = """基于以下音频转录文本，分析直播内容：

转录文本：
{transcript}

请提供以下信息（以 JSON 格式返回）：
1. audio_theme: 话题或内容主题
2. audio_emotion: 主播情绪状态（excited/calm/happy/angry/sad/neutral）
3. audio_keywords: 3-5个关键词
4. audio_quality: 内容质量评分（0-1），基于对话有趣程度
5. audio_highlights: 对话中的精彩片段或金句
"""


def extract_audio(video_path: str) -> str:
    """从视频提取音频

    Args:
        video_path: 视频文件路径

    Returns:
        str: 提取的音频文件路径
    """
    temp_dir = tempfile.mkdtemp(prefix="bilive_audio_")
    audio_path = os.path.join(temp_dir, "audio.wav")

    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",  # 不包含视频
            "-acodec", "pcm_s16le",  # WAV 格式
            "-ar", "16000",  # 16kHz 采样率（Whisper 推荐）
            "-ac", "1",  # 单声道
            audio_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        scan_log.info(f"Extracted audio from {video_path} to {audio_path}")
        return audio_path

    except subprocess.CalledProcessError as e:
        scan_log.error(f"ffmpeg audio extraction failed: {e.stderr.decode()}")
        return ""
    except FileNotFoundError:
        scan_log.error("ffmpeg not found, please install ffmpeg")
        return ""


def transcribe_audio_whisper(audio_path: str, model_size: str = "base") -> Dict[str, Any]:
    """使用本地 Whisper 模型转录音频

    Args:
        audio_path: 音频文件路径
        model_size: Whisper 模型大小 (tiny/base/small/medium/large)

    Returns:
        Dict: 转录结果，包含文本和元数据
    """
    try:
        import whisper
    except ImportError:
        scan_log.error("Whisper not installed. Run: pip install openai-whisper")
        return {"transcript": "", "error": "whisper_not_installed"}

    try:
        scan_log.info(f"Loading Whisper model: {model_size}")
        model = whisper.load_model(model_size)

        scan_log.info(f"Transcribing audio: {audio_path}")
        result = model.transcribe(audio_path, language="zh")

        transcript = result.get("text", "")
        segments = result.get("segments", [])

        scan_log.info(f"Transcription complete: {len(transcript)} chars, {len(segments)} segments")

        return {
            "transcript": transcript,
            "segments": segments,
            "language": result.get("language", "zh")
        }

    except Exception as e:
        scan_log.error(f"Whisper transcription failed: {e}")
        return {"transcript": "", "error": str(e)}


def analyze_audio_content(transcript: str) -> Dict[str, Any]:
    """分析转录内容

    Args:
        transcript: 转录文本

    Returns:
        Dict: 分析结果
    """
    if not transcript or len(transcript) < 10:
        scan_log.warning("Transcript too short for analysis")
        return {
            "audio_theme": "未知",
            "audio_emotion": "neutral",
            "audio_keywords": [],
            "audio_quality": 0.3,
            "audio_highlights": []
        }

    # 简单关键词分析
    keywords = extract_keywords(transcript)

    # 情感分析（简单启发式）
    emotion = detect_emotion(transcript)

    return {
        "audio_theme": "直播内容",
        "audio_emotion": emotion,
        "audio_keywords": keywords,
        "audio_quality": 0.5,
        "audio_highlights": []
    }


def extract_keywords(text: str, max_keywords: int = 5) -> list:
    """提取关键词（简单实现）"""
    # 基于词频的简单提取
    import re
    words = re.findall(r'\b[一-龥]{2,4}\b', text)
    word_freq = {}
    for word in words:
        word_freq[word] = word_freq.get(word, 0) + 1

    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]


def detect_emotion(text: str) -> str:
    """检测情绪（简单启发式）"""
    emotion_keywords = {
        "excited": ["哈哈", "好棒", "太强了", "厉害", "牛逼", "太好了", "开心"],
        "happy": ["谢谢", "喜欢", "快乐", "幸福", "可爱"],
        "angry": ["生气", "讨厌", "烦人", "无语", "气死"],
        "sad": ["难过", "伤心", "遗憾", "可惜", "唉"],
        "calm": ["嗯", "好的", "明白", "清楚", "理解"]
    }

    for emotion, keywords in emotion_keywords.items():
        for kw in keywords:
            if kw in text:
                return emotion

    return "neutral"


def cleanup_audio(audio_path: str) -> None:
    """清理临时音频文件"""
    if audio_path and os.path.exists(audio_path):
        temp_dir = os.path.dirname(audio_path)
        try:
            os.remove(audio_path)
            os.rmdir(temp_dir)
            scan_log.info("Cleaned up temporary audio file")
        except OSError:
            pass


def release_gpu_memory(delay: float = 3.0) -> None:
    """释放 GPU 显存

    Args:
        delay: 等待时间（秒），确保显存完全释放
    """
    import time
    try:
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            scan_log.info("GPU memory cache cleared")
    except ImportError:
        scan_log.warning("torch not available for GPU memory release")

    time.sleep(delay)
    scan_log.info(f"GPU memory release completed (waited {delay}s)")


def load_emotion_model(model_name: str = "facebook/wav2vec2-base-robust-emotion") -> tuple:
    """加载音频情感识别模型

    Args:
        model_name: HuggingFace 模型名称
            - facebook/wav2vec2-base-robust-emotion (通用情感)
            - 或其他 wav2vec2 微调版本

    Returns:
        tuple: (model, processor) 或 (None, None) 失败时
    """
    global _emotion_model, _emotion_processor

    if _emotion_model is not None and _emotion_processor is not None:
        scan_log.info("Using cached emotion model")
        return _emotion_model, _emotion_processor

    try:
        from transformers import Wav2Vec2ForSequenceClassification, Wav2Vec2Processor

        scan_log.info(f"Loading emotion model: {model_name}")
        processor = Wav2Vec2Processor.from_pretrained(model_name)
        model = Wav2Vec2ForSequenceClassification.from_pretrained(model_name)

        # 缓存模型
        _emotion_model = model
        _emotion_processor = processor

        scan_log.info(f"Emotion model loaded successfully")
        return model, processor

    except ImportError:
        scan_log.error("transformers not installed. Run: pip install transformers")
        return None, None
    except Exception as e:
        scan_log.error(f"Failed to load emotion model: {e}")
        return None, None


def detect_emotion_with_model(
    audio_path: str,
    model_name: str = "facebook/wav2vec2-base-robust-emotion"
) -> Dict[str, Any]:
    """使用深度模型检测音频情感

    Args:
        audio_path: 音频文件路径（WAV 格式，16kHz）
        model_name: 情感模型名称

    Returns:
        Dict: 情感分析结果
    """
    model, processor = load_emotion_model(model_name)

    if model is None or processor is None:
        scan_log.warning("Emotion model unavailable, falling back to heuristic")
        return {"emotion": "neutral", "emotion_confidence": 0.3, "error": "model_unavailable"}

    try:
        import librosa
        import torch

        # 加载音频
        scan_log.info(f"Analyzing emotion for: {audio_path}")
        audio, sr = librosa.load(audio_path, sr=16000)

        # 预处理
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt", padding=True)

        # 推理
        with torch.no_grad():
            logits = model(**inputs).logits
            predicted_id = torch.argmax(logits, dim=-1).item()

        # 获取情感标签
        emotion_label = model.config.id2label.get(predicted_id, "unknown")

        # 计算置信度
        probs = torch.softmax(logits, dim=-1)
        confidence = probs[0][predicted_id].item()

        scan_log.info(f"Detected emotion: {emotion_label} (confidence: {confidence:.2f})")

        return {
            "emotion": emotion_label,
            "emotion_confidence": confidence,
            "all_emotions": {model.config.id2label[i]: probs[0][i].item() for i in range(len(probs[0]))}
        }

    except Exception as e:
        scan_log.error(f"Emotion detection failed: {e}")
        return {"emotion": "neutral", "emotion_confidence": 0.3, "error": str(e)}


def unload_emotion_model() -> None:
    """卸载情感模型，释放显存"""
    global _emotion_model, _emotion_processor

    if _emotion_model is not None:
        del _emotion_model
        _emotion_model = None

    if _emotion_processor is not None:
        del _emotion_processor
        _emotion_processor = None

    release_gpu_memory()
    scan_log.info("Emotion model unloaded, GPU memory released")


def analyze_audio(
    video_path: str,
    whisper_model: str = "base",
    enable_emotion: bool = False,
    emotion_model: str = "facebook/wav2vec2-base-robust-emotion"
) -> Dict[str, Any]:
    """完整的音频分析流程

    Args:
        video_path: 视频文件路径
        whisper_model: Whisper 模型大小 (tiny/base/small/medium/large)
        enable_emotion: 是否启用深度情感分析
        emotion_model: 情感识别模型名称

    Returns:
        Dict: 音频分析结果
    """
    # 1. 提取音频
    audio_path = extract_audio(video_path)
    if not audio_path:
        return {"error": "audio_extraction_failed"}

    result = {}

    # 2. Whisper 转录
    transcript_result = transcribe_audio_whisper(audio_path, whisper_model)
    result["transcript"] = transcript_result.get("transcript", "")
    result["segments"] = transcript_result.get("segments", [])

    # 3. 情感分析（可选）
    if enable_emotion:
        emotion_result = detect_emotion_with_model(audio_path, emotion_model)
        result["emotion"] = emotion_result.get("emotion", "neutral")
        result["emotion_confidence"] = emotion_result.get("emotion_confidence", 0.3)
        result["all_emotions"] = emotion_result.get("all_emotions", {})
    else:
        # 使用启发式情感分析
        content_analysis = analyze_audio_content(result["transcript"])
        result["emotion"] = content_analysis.get("audio_emotion", "neutral")
        result["audio_keywords"] = content_analysis.get("audio_keywords", [])
        result["audio_quality"] = content_analysis.get("audio_quality", 0.5)

    # 4. 清理临时文件
    cleanup_audio(audio_path)

    return result