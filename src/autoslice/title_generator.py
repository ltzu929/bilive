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