#!/bin/bash
# agent.sh — 在树莓派上启动录制+扫描 agent
#
# 用法:
#   ./agent.sh                    # 使用默认配置
#   BILIVE_VIDEOS_DIR=/mnt/win/bilive/Videos ./agent.sh  # 指定 NFS 挂载路径
#
# 环境变量:
#   BILIVE_CONFIG      — agent 配置文件路径 (默认: ./bilive-agent.toml)
#   BILIVE_VIDEOS_DIR  — 视频输出目录 (默认: /mnt/win/bilive/Videos)
#   BILIVE_LOG_DIR     — 日志目录 (默认: /mnt/win/bilive/logs)
#   BILIVE_VENV_DIR    — Python 虚拟环境路径 (默认: ./venv)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 激活 Python 环境：优先 conda，回退 venv
CONDA_SH="$HOME/miniforge/etc/profile.d/conda.sh"
if [ -f "$CONDA_SH" ]; then
    source "$CONDA_SH" && conda activate bilive
else
    VENV_DIR="${BILIVE_VENV_DIR:-$PROJECT_DIR/venv}"
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    else
        echo "No Python environment found. Install conda or create venv."
        exit 1
    fi
fi

export PYTHONPATH=./src
export BILIVE_CONFIG="${BILIVE_CONFIG:-$PROJECT_DIR/bilive-agent.toml}"
export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-/mnt/win/bilive/Videos}"
export BILIVE_LOG_DIR="${BILIVE_LOG_DIR:-/mnt/win/bilive/logs}"

# 确保输出目录存在（NFS 挂载）
mkdir -p "$BILIVE_VIDEOS_DIR" "$BILIVE_LOG_DIR/runtime" "$BILIVE_LOG_DIR/scan"

# 停止旧进程
pkill -f 'src.agent.scanner' 2>/dev/null || true

# 启动扫描器
nohup python -m src.agent.scanner > "$BILIVE_LOG_DIR/scanner-$(date +%Y%m%d-%H%M%S).log" 2>&1 &

echo "Agent started."
echo "  Videos dir: $BILIVE_VIDEOS_DIR"
echo "  Log dir:    $BILIVE_LOG_DIR"
echo "  Config:     $BILIVE_CONFIG"
echo ""
echo "Note: blrec should be started separately via record.sh or record-pi.sh"