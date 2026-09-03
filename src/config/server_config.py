"""Production configuration for the Windows processing pipeline."""

from __future__ import annotations

import os

from .base import (
    BILIVE_DIR,
    DB_PATH,
    LOG_DIR,
    SRC_DIR,
    VIDEOS_DIR,
    load_config_from_toml,
)


_config_path = os.environ.get(
    "BILIVE_CONFIG",
    os.path.join(BILIVE_DIR, "bilive-server.toml"),
)
config = load_config_from_toml(_config_path)
if config is None:
    raise RuntimeError(f"Cannot load bilive configuration: {_config_path}")

video = config.get("video", {})
upload = config.get("upload", {})
worker = config.get("worker", {})
slice_config = config.get("slice", {})
burst = slice_config.get("burst", {})
judge = slice_config.get("llm_judge", {})
multi_modal = slice_config.get("multi_modal", {})
mimo = slice_config.get("mimo", {})
quality = slice_config.get("quality", {})
analysis = slice_config.get("analysis", {})
edit = slice_config.get("edit", {})
subtitle = slice_config.get("subtitle", {})

TITLE = video.get("title", "{artist}直播-{date}")
DESC = video.get("description", "直播录制切片")
TID = int(video.get("tid", 138))
UPLOAD_LINE = str(video.get("upload_line", "auto"))

UPLOAD_AUTO_START = bool(upload.get("auto_start", True))
UPLOAD_POLL_INTERVAL_SECONDS = float(upload.get("poll_interval_seconds", 10))
UPLOAD_MAX_ATTEMPTS = int(upload.get("max_attempts", 3))
UPLOAD_RETRY_BASE_SECONDS = float(upload.get("retry_base_seconds", 30))
UPLOAD_AUTH_RETRY_SECONDS = float(upload.get("auth_retry_seconds", 120))
UPLOAD_DELETE_AFTER_SUCCESS = bool(upload.get("delete_after_success", True))

WORKER_IDLE_TIMEOUT_SECONDS = float(
    os.environ.get(
        "BILIVE_WORKER_IDLE_TIMEOUT",
        worker.get("idle_timeout_seconds", 900),
    )
)
WORKER_IDLE_CHECK_INTERVAL_SECONDS = float(
    os.environ.get(
        "BILIVE_WORKER_IDLE_CHECK_INTERVAL",
        worker.get("idle_check_interval_seconds", 30),
    )
)

MIN_VIDEO_SIZE = float(slice_config.get("min_video_size", 20))
BURST_RATIO = float(burst.get("burst_ratio", 3.0))
BURST_WINDOW = int(burst.get("burst_window", 10))
BURST_CONTEXT = int(burst.get("burst_context", 60))
BURST_MERGE_GAP = int(burst.get("burst_merge_gap", 5))
BURST_TOP_N = int(burst.get("burst_top_n", 3))
BURST_LAG_SECONDS = float(
    os.environ.get("BILIVE_BURST_LAG_SECONDS", burst.get("burst_lag_seconds", 0.0))
)
DANMAKU_TIMELINE = str(
    os.environ.get(
        "BILIVE_DANMAKU_TIMELINE",
        burst.get("danmaku_timeline", True),
    )
).strip().lower() in {"1", "true", "yes", "on"}
DANMAKU_MAX_CHARS = int(
    os.environ.get(
        "BILIVE_DANMAKU_MAX_CHARS",
        burst.get("danmaku_max_chars", 4000),
    )
)

LLM_JUDGE_PROVIDER = str(judge.get("provider", "openai-compatible"))
LOCAL_LLM_COMMAND = list(judge.get("local_command", []))
LOCAL_LLM_TIMEOUT = float(judge.get("timeout", 120))
MANAGED_LLM_MODEL_PATH = os.environ.get(
    "BILIVE_LLM_MODEL_PATH",
    str(judge.get("model_path", "")),
)
MANAGED_LLAMA_SERVER_PATH = os.environ.get(
    "BILIVE_LLAMA_SERVER_PATH",
    str(judge.get("server_path", "")),
)
MANAGED_LLAMA_HOST = str(judge.get("host", "127.0.0.1"))
MANAGED_LLAMA_PORT = int(judge.get("port", 2236))
MANAGED_LLAMA_CONTEXT_SIZE = int(judge.get("context_size", 4096))
MANAGED_LLAMA_GPU_LAYERS = str(judge.get("gpu_layers", "all"))
MANAGED_LLAMA_PARALLEL = int(judge.get("parallel", 1))
MANAGED_LLAMA_STARTUP_TIMEOUT = float(judge.get("startup_timeout", 180))
MANAGED_LLAMA_SHUTDOWN_TIMEOUT = float(judge.get("shutdown_timeout", 15))

MULTI_MODAL_VISUAL_URL = str(
    multi_modal.get("visual_model_url", "http://127.0.0.1:2236/v1")
)
MULTI_MODAL_VISUAL_NAME = str(
    multi_modal.get("visual_model_name", "local-model")
)
MULTI_MODAL_WHISPER_MODEL = str(
    multi_modal.get("whisper_model", "large-v3")
)
WHISPER_ENGINE = str(multi_modal.get("whisper_engine", "faster-whisper"))
WHISPER_DEVICE = str(multi_modal.get("whisper_device", "cpu"))
WHISPER_COMPUTE_TYPE = str(
    multi_modal.get("whisper_compute_type", "int8")
)
WHISPER_BATCH_SIZE = int(
    os.environ.get(
        "BILIVE_WHISPER_BATCH_SIZE",
        multi_modal.get("whisper_batch_size", 8),
    )
)
WHISPER_CPU_THREADS = int(
    os.environ.get(
        "BILIVE_WHISPER_CPU_THREADS",
        multi_modal.get("whisper_cpu_threads", 8),
    )
)
WHISPER_VAD_FILTER = str(
    os.environ.get(
        "BILIVE_WHISPER_VAD_FILTER",
        multi_modal.get("whisper_vad_filter", True),
    )
).strip().lower() in {"1", "true", "yes", "on"}
WHISPER_VAD_MIN_SILENCE_MS = int(
    os.environ.get(
        "BILIVE_WHISPER_VAD_MIN_SILENCE_MS",
        multi_modal.get("whisper_vad_min_silence_ms", 2000),
    )
)
WHISPER_VAD_SPEECH_PAD_MS = int(
    os.environ.get(
        "BILIVE_WHISPER_VAD_SPEECH_PAD_MS",
        multi_modal.get("whisper_vad_speech_pad_ms", 400),
    )
)
MULTI_MODAL_UNLOAD_AUDIO_MODEL = bool(
    multi_modal.get("unload_audio_model_after_analysis", True)
)

MIMO_MODEL = str(mimo.get("model", "mimo-v2.5"))
MIMO_BASE_URL = str(mimo.get("base_url", "https://api.xiaomimimo.com/v1"))
MIMO_FPS = float(mimo.get("fps", 1.0))
MIMO_MEDIA_RESOLUTION = str(mimo.get("media_resolution", "default"))
MIMO_TIMEOUT = float(mimo.get("timeout", 180))
MIMO_REQUEST_PARALLELISM = int(
    os.environ.get(
        "BILIVE_MIMO_REQUEST_PARALLELISM",
        mimo.get("request_parallelism", mimo.get("parallelism", 3)),
    )
)
# Kept as a public compatibility alias for dashboard and older callers.
MIMO_PARALLELISM = MIMO_REQUEST_PARALLELISM
MIMO_ENCODE_PARALLELISM = int(
    os.environ.get(
        "BILIVE_MIMO_ENCODE_PARALLELISM",
        mimo.get("encode_parallelism", 1),
    )
)
MIMO_MAX_BASE64_BYTES = int(mimo.get("max_base64_bytes", 48_000_000))

OMNI_ENABLE_DEEP_ANALYSIS = bool(
    analysis.get("write_analysis_json", True)
)

# 将 MiMo 返回的 trim 端点吸附到附近的 ASR 分段边界。
# 只转写 trim 前后的小范围音频，并复用同一次转录生成字幕。
SNAP_TRIM_TO_SEGMENTS = str(
    os.environ.get("BILIVE_SNAP_TRIM", analysis.get("snap_trim_to_segments", ""))
).strip().lower() in {"1", "true", "yes", "on"}
SNAP_TRIM_TOLERANCE = float(
    os.environ.get(
        "BILIVE_SNAP_TRIM_TOLERANCE", analysis.get("snap_trim_tolerance", 3.0)
    )
)
TRIM_ASR_PADDING_SECONDS = float(
    os.environ.get(
        "BILIVE_TRIM_ASR_PADDING_SECONDS",
        analysis.get("trim_asr_padding_seconds", 6.0),
    )
)
MIN_QUALITY_SCORE = float(
    os.environ.get(
        "BILIVE_MIN_QUALITY_SCORE",
        quality.get(
            "min_quality_score",
            analysis.get("min_quality_score", mimo.get("min_quality_score", 0.80)),
        ),
    )
)
MIN_COMPLETENESS_SCORE = float(
    os.environ.get(
        "BILIVE_MIN_COMPLETENESS_SCORE",
        quality.get(
            "min_completeness_score",
            analysis.get(
                "min_completeness_score",
                mimo.get("min_completeness_score", 0.80),
            ),
        ),
    )
)
MIN_CONFIDENCE = float(
    os.environ.get(
        "BILIVE_MIN_CONFIDENCE",
        quality.get(
            "min_confidence",
            analysis.get("min_confidence", mimo.get("min_confidence", 0.80)),
        ),
    )
)

EDIT_ENABLE_INSTRUCTION = bool(edit.get("enable_edit_instruction", True))
EDIT_ENABLE_PROMPT_PACKAGE = bool(edit.get("enable_prompt_package", False))
EDIT_MAX_SUBTITLE_EVIDENCE = int(edit.get("max_subtitle_evidence", 6))
EDIT_DEFAULT_HIGHLIGHT_WINDOW = float(
    edit.get("default_highlight_window", 12)
)


# 硬烧字幕外观参数（全局默认，可被单切片 task.json 覆盖）。
def _subtitle_opt_int(key: str):
    value = subtitle.get(key)
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _subtitle_opt_float(key: str):
    value = subtitle.get(key)
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _subtitle_opt_str(key: str):
    value = subtitle.get(key)
    text = str(value).strip() if value is not None else ""
    return text or None


SUBTITLE_FONT_NAME = _subtitle_opt_str("font_name") or "Noto Sans SC"
SUBTITLE_FONT_SIZE = int(subtitle.get("font_size", 20))
SUBTITLE_MARGIN_V = int(subtitle.get("margin_v", 60))
SUBTITLE_ALIGNMENT = _subtitle_opt_int("alignment")
SUBTITLE_OUTLINE = _subtitle_opt_float("outline")
SUBTITLE_PRIMARY_COLOUR = _subtitle_opt_str("primary_colour")
SUBTITLE_OUTLINE_COLOUR = _subtitle_opt_str("outline_colour")


def default_subtitle_style():
    """Build the global default SubtitleStyle from configuration."""
    from src.burn.subtitle_burn import SubtitleStyle

    return SubtitleStyle(
        font_name=SUBTITLE_FONT_NAME,
        font_size=SUBTITLE_FONT_SIZE,
        margin_v=SUBTITLE_MARGIN_V,
        alignment=SUBTITLE_ALIGNMENT,
        outline=SUBTITLE_OUTLINE,
        primary_colour=SUBTITLE_PRIMARY_COLOUR,
        outline_colour=SUBTITLE_OUTLINE_COLOUR,
    )
