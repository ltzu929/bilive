from functools import wraps
from src.log.logger import scan_log
from src.config import MLLM_MODEL


def title_generator(model_type):
    """Decorator to select title generation function based on model type
    Args:
        model_type: str, type of model to use
    Returns:
        function: wrapped title generation function
    """

    def decorator(func):
        def wrapper(video_path, artist):
            if model_type == "zhipu":
                from .mllm_sdk.zhipu_sdk import zhipu_glm_4v_plus_generate_title
                return zhipu_glm_4v_plus_generate_title(video_path, artist)

            elif model_type == "gemini":
                from .mllm_sdk.gemini_old_sdk import gemini_generate_title
                return gemini_generate_title(video_path, artist)

            elif model_type == "qwen":
                from .mllm_sdk.qwen_sdk import qwen_generate_title
                return qwen_generate_title(video_path, artist)

            elif model_type == "sensenova":
                from .mllm_sdk.sensenova_sdk import sensenova_generate_title
                return sensenova_generate_title(video_path, artist)

            elif model_type == "qwen-omni":
                from .mllm_sdk.qwen_omni_sdk import qwen_omni_analyze
                return qwen_omni_analyze(video_path, artist)

            elif model_type == "multi-modal":
                from .mllm_sdk.multi_modal_analyzer import multi_modal_analyze
                from src.config import (
                    MULTI_MODAL_VISUAL_URL,
                    MULTI_MODAL_VISUAL_NAME,
                    MULTI_MODAL_WHISPER_MODEL,
                    MULTI_MODAL_FRAME_FPS,
                    MULTI_MODAL_ENABLE_VISUAL,
                    MULTI_MODAL_ENABLE_AUDIO,
                    MULTI_MODAL_ENABLE_EMOTION_ANALYSIS,
                    MULTI_MODAL_EMOTION_MODEL
                )
                return multi_modal_analyze(
                    video_path, artist,
                    visual_model_url=MULTI_MODAL_VISUAL_URL,
                    visual_model_name=MULTI_MODAL_VISUAL_NAME,
                    frame_fps=MULTI_MODAL_FRAME_FPS,
                    whisper_model=MULTI_MODAL_WHISPER_MODEL,
                    enable_visual=MULTI_MODAL_ENABLE_VISUAL,
                    enable_audio=MULTI_MODAL_ENABLE_AUDIO,
                    enable_emotion=MULTI_MODAL_ENABLE_EMOTION_ANALYSIS,
                    emotion_model=MULTI_MODAL_EMOTION_MODEL
                )

            elif model_type == "local-audio":
                # 纯音频分析模式（8G 显存适配）
                from .mllm_sdk.multi_modal_analyzer import multi_modal_analyze
                from src.config import (
                    MULTI_MODAL_WHISPER_MODEL,
                    MULTI_MODAL_ENABLE_EMOTION_ANALYSIS,
                    MULTI_MODAL_EMOTION_MODEL
                )
                return multi_modal_analyze(
                    video_path, artist,
                    whisper_model=MULTI_MODAL_WHISPER_MODEL,
                    enable_visual=False,  # 不启用视觉分析
                    enable_audio=True,
                    enable_emotion=MULTI_MODAL_ENABLE_EMOTION_ANALYSIS,
                    emotion_model=MULTI_MODAL_EMOTION_MODEL
                )

            else:
                scan_log.error(f"Unsupported model type: {model_type}")
                return None

        return wrapper

    return decorator


@title_generator(MLLM_MODEL)
def generate_title(video_path, artist):
    """Generate title for video
    Args:
        video_path: str, path to the video file
        artist: str, artist name
    Returns:
        - str: 当使用普通 MLLM 模型时，返回标题字符串
        - AnalysisResult: 当使用 qwen-omni 时，返回完整分析结果对象
    """
    pass


def extract_title(result):
    """从生成结果中提取标题
    Args:
        result: str 或 AnalysisResult
    Returns:
        str: 标题字符串，无效输入返回 None
    """
    if isinstance(result, str):
        return result
    from .analysis_result import AnalysisResult
    if isinstance(result, AnalysisResult):
        return result.title
    return None