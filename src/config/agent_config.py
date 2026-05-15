# src/config/agent_config.py
# Pi 端精简配置 — 无 torch/GPU/模型依赖
#
# 只包含录制、扫描、视频元数据相关的配置

import os
from .base import load_config_from_toml, BILIVE_DIR, SRC_DIR

# ── 加载配置文件 ──
_config_path = os.environ.get("BILIVE_CONFIG", os.path.join(BILIVE_DIR, "bilive-agent.toml"))
config = load_config_from_toml(_config_path)
if config is None:
    print("failed to load agent config file, please check bilive-agent.toml", flush=True)
    exit(1)

# ── 路径配置（可被环境变量覆盖）──
from .base import VIDEOS_DIR, LOG_DIR  # noqa: F401

# ── 录制配置 ──
ROOM_IDS = config.get("recording", {}).get("room_ids", [])

# ── 扫描配置 ──
SCAN_INTERVAL = config.get("scan", {}).get("interval", 120)
MIN_VIDEO_SIZE = config.get("scan", {}).get("min_video_size", 20)

# ── 视频元数据（写入 .pending 标记用）──
TITLE = config.get("video", {}).get("title", "")
DESC = config.get("video", {}).get("description", "")
TID = config.get("video", {}).get("tid", 138)
GIFT_PRICE_FILTER = config.get("video", {}).get("gift_price_filter", 1)
UPLOAD_LINE = config.get("video", {}).get("upload_line", "auto")