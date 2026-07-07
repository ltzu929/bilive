# src/config/base.py
# 共享配置加载逻辑 — 无 torch 依赖，Pi 和 PC 都可安全导入
#
# 路径优先级: 环境变量 > 配置文件 > 默认值

import logging
import os
from pathlib import Path
import toml


logger = logging.getLogger("bilive.config")


def load_config_from_toml(file_path):
    """从 toml 文件加载配置，返回 dict 或 None"""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            config = toml.load(file)
            return config
    except FileNotFoundError:
        logger.error("cannot find config file: %s", file_path)
    except toml.TomlDecodeError as e:
        logger.error("cannot parse %s as a valid toml file, error: %s", file_path, e)
    except Exception:
        logger.exception("unknown error when loading config file: %s", file_path)
    return None


# ── 路径配置 ──
# 全部可通过环境变量覆盖，方便 Pi/PC 使用不同挂载路径

# src/config/base.py 的位置 → src/ → project root
_CONFIG_FILE = Path(__file__).resolve()                  # src/config/base.py
_SRC_DIR = str(_CONFIG_FILE.parent.parent)              # src/
_BILIVE_DIR = str(_CONFIG_FILE.parent.parent.parent)    # project root

SRC_DIR = os.environ.get("BILIVE_SRC_DIR", _SRC_DIR)
BILIVE_DIR = os.environ.get("BILIVE_DIR", _BILIVE_DIR)
LOG_DIR = os.environ.get("BILIVE_LOG_DIR", os.path.join(BILIVE_DIR, "logs"))
VIDEOS_DIR = os.environ.get("BILIVE_VIDEOS_DIR", os.path.join(BILIVE_DIR, "Videos"))
DB_PATH = os.environ.get("BILIVE_DB_PATH", os.path.join(SRC_DIR, "db", "data.db"))