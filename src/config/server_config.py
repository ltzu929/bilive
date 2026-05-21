# src/config/server_config.py
# PC 端完整配置 — 包含所有模型、GPU、ASR、切片等配置
#
# GPU 检测使用 lazy import，在无 torch 环境下不会崩溃（返回 False）

import os
import configparser
from pathlib import Path
from .base import load_config_from_toml, SRC_DIR, BILIVE_DIR, VIDEOS_DIR, LOG_DIR, DB_PATH


# ── GPU 检测 — lazy import，无 torch 时返回 False ──
def _check_gpu():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ── 加载配置文件 ──
_config_path = os.environ.get("BILIVE_CONFIG", os.path.join(BILIVE_DIR, "bilive-server.toml"))
config = load_config_from_toml(_config_path)
if config is None:
    print("failed to load server config file, please check bilive-server.toml", flush=True)
    exit(1)

# ── 初始化数据库 ──
if not os.path.exists(DB_PATH):
    print("Initialize the database", flush=True)
    from db.conn import create_table
    create_table()


# ── 模型配置 ──
GPU_EXIST = _check_gpu()
MODEL_TYPE = config.get("model", {}).get("model_type")

# ── ASR 配置 ──
ASR_METHOD = config.get("asr", {}).get("asr_method")
WHISPER_API_KEY = config.get("asr", {}).get("whisper_api_key")
INFERENCE_MODEL = config.get("asr", {}).get("inference_model")


def get_model_path():
    model_dir = os.path.join(SRC_DIR, "subtitle", "models")
    model_path = os.path.join(model_dir, f"{INFERENCE_MODEL}.pt")
    return model_path


def get_interface_config():
    interface_config = configparser.ConfigParser()
    interface_dir = os.path.join(SRC_DIR, "subtitle")
    interface_file = os.path.join(interface_dir, "en.ini")
    interface_config.read(interface_file, encoding="utf-8")
    return interface_config


# ── 视频配置 ──
TITLE = config.get("video", {}).get("title")
DESC = config.get("video", {}).get("description")
TID = config.get("video", {}).get("tid")
GIFT_PRICE_FILTER = config.get("video", {}).get("gift_price_filter")
RESERVE_FOR_FIXING = config.get("video", {}).get("reserve_for_fixing")
UPLOAD_LINE = config.get("video", {}).get("upload_line")

# ── 切片配置 ──
AUTO_SLICE = config.get("slice", {}).get("auto_slice")
SLICE_DURATION = config.get("slice", {}).get("slice_duration")
SLICE_NUM = config.get("slice", {}).get("slice_num")
SLICE_OVERLAP = config.get("slice", {}).get("slice_overlap")
SLICE_STEP = config.get("slice", {}).get("slice_step")
SLICE_PRE_CONTEXT = config.get("slice", {}).get("slice_pre_context", 30)
SLICE_POST_CONTEXT = config.get("slice", {}).get("slice_post_context", 40)
MIN_VIDEO_SIZE = config.get("slice", {}).get("min_video_size")
MLLM_MODEL = config.get("slice", {}).get("mllm_model")
ZHIPU_API_KEY = config.get("slice", {}).get("zhipu_api_key")
GEMINI_API_KEY = config.get("slice", {}).get("gemini_api_key")
QWEN_API_KEY = config.get("slice", {}).get("qwen_api_key")
SENSENOVA_API_KEY = config.get("slice", {}).get("sensenova_api_key")

# ── 封面配置 ──
GENERATE_COVER = config.get("cover", {}).get("generate_cover")
IMAGE_GEN_MODEL = config.get("cover", {}).get("image_gen_model")
MINIMAX_API_KEY = config.get("cover", {}).get("minimax_api_key")
SILICONFLOW_API_KEY = config.get("cover", {}).get("siliconflow_api_key")
TENCENT_SECRET_ID = config.get("cover", {}).get("tencent_secret_id")
TENCENT_SECRET_KEY = config.get("cover", {}).get("tencent_secret_key")
BAIDU_API_KEY = config.get("cover", {}).get("baidu_api_key")
STABILITY_API_KEY = config.get("cover", {}).get("stability_api_key")
LUMA_API_KEY = config.get("cover", {}).get("luma_api_key")
IDEOGRAM_API_KEY = config.get("cover", {}).get("ideogram_api_key")
RECRAFT_API_KEY = config.get("cover", {}).get("recraft_api_key")
AWS_ACCESS_KEY_ID = config.get("cover", {}).get("aws_access_key_id")
AWS_SECRET_ACCESS_KEY = config.get("cover", {}).get("aws_secret_access_key")
HIDREAM_API_KEY = config.get("cover", {}).get("hidream_api_key")
DMX_API_TOKEN = config.get("cover", {}).get("dmx_api_token")
SLICE_PROMPT = config.get("slice", {}).get("slice_prompt")
COVER_PROMPT = config.get("cover", {}).get("cover_prompt")

# ── OMNI 分析配置 ──
OMNI_ENABLE_QUALITY_FILTER = config.get("slice", {}).get("omni", {}).get("enable_quality_filter", True)
OMNI_QUALITY_THRESHOLD = config.get("slice", {}).get("omni", {}).get("quality_threshold", 0.6)
OMNI_ENABLE_DEEP_ANALYSIS = config.get("slice", {}).get("omni", {}).get("enable_deep_analysis", True)
OMNI_ANALYSIS_PROMPT = config.get("slice", {}).get("omni", {}).get("analysis_prompt", "")

# ── 多模型协作配置 ──
MULTI_MODAL_VISUAL_URL = config.get("slice", {}).get("multi_modal", {}).get("visual_model_url", "http://localhost:1234/v1")
MULTI_MODAL_VISUAL_NAME = config.get("slice", {}).get("multi_modal", {}).get("visual_model_name", "local-model")
MULTI_MODAL_WHISPER_MODEL = config.get("slice", {}).get("multi_modal", {}).get("whisper_model", "base")
MULTI_MODAL_FRAME_FPS = config.get("slice", {}).get("multi_modal", {}).get("frame_fps", 0.5)
MULTI_MODAL_ENABLE_VISUAL = config.get("slice", {}).get("multi_modal", {}).get("enable_visual", True)
MULTI_MODAL_ENABLE_AUDIO = config.get("slice", {}).get("multi_modal", {}).get("enable_audio", True)
WHISPER_ENGINE = config.get("slice", {}).get("multi_modal", {}).get("whisper_engine", "openai-whisper")
WHISPER_DEVICE = config.get("slice", {}).get("multi_modal", {}).get("whisper_device", "cpu")
WHISPER_COMPUTE_TYPE = config.get("slice", {}).get("multi_modal", {}).get("whisper_compute_type", "int8")

# ── 情感分析配置 ──
MULTI_MODAL_ENABLE_EMOTION_ANALYSIS = config.get("slice", {}).get("multi_modal", {}).get("enable_emotion_analysis", False)
MULTI_MODAL_EMOTION_MODEL = config.get("slice", {}).get("multi_modal", {}).get("emotion_model", "facebook/wav2vec2-base-robust-emotion")

# ── 切片方法配置 ──
SLICE_METHOD = config.get("slice", {}).get("slice_method", "density")  # "density" 或 "burst"
BURST_RATIO = config.get("slice", {}).get("burst", {}).get("burst_ratio", 3.0)
BURST_WINDOW = config.get("slice", {}).get("burst", {}).get("burst_window", 10)
BURST_CONTEXT = config.get("slice", {}).get("burst", {}).get("burst_context", 60)
BURST_MERGE_GAP = config.get("slice", {}).get("burst", {}).get("burst_merge_gap", 5)
BURST_TOP_N = config.get("slice", {}).get("burst", {}).get("burst_top_n", 3)

# ── Edit instruction 配置 ──
EDIT_ENABLE_INSTRUCTION = config.get("slice", {}).get("edit", {}).get("enable_edit_instruction", True)
EDIT_ENABLE_PROMPT_PACKAGE = config.get("slice", {}).get("edit", {}).get("enable_prompt_package", False)
EDIT_MAX_SUBTITLE_EVIDENCE = config.get("slice", {}).get("edit", {}).get("max_subtitle_evidence", 6)
EDIT_DEFAULT_HIGHLIGHT_WINDOW = config.get("slice", {}).get("edit", {}).get("default_highlight_window", 12)