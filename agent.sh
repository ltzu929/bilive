#!/bin/bash
# agent.sh — 在树莓派上启动录制+扫描 agent
#
# 用法:
#   ./agent.sh                    # 使用默认配置
#   BILIVE_VIDEOS_DIR=/mnt/bilive/Videos ./agent.sh  # 指定 NFS 挂载路径
#
# 环境变量:
#   BILIVE_CONFIG      — agent 配置文件路径 (默认: ./bilive-agent.toml)
#   BILIVE_VIDEOS_DIR  — 视频输出目录 (默认: /mnt/bilive/Videos)
#   BILIVE_LOG_DIR     — 日志目录 (默认: /mnt/bilive/logs)
#   BILIVE_VENV_DIR    — Python 虚拟环境路径 (默认: ./venv)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 激活虚拟环境（Pi 端轻量 venv，不含 torch 等重型依赖）
VENV_DIR="${BILIVE_VENV_DIR:-$PROJECT_DIR/venv}"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Python venv not found: $VENV_DIR"
    echo "On Pi, create a minimal venv: python3 -m venv venv && source venv/bin/activate && pip install -r requirements-agent.txt"
    exit 1
fi
source "$VENV_DIR/bin/activate"

export PYTHONPATH=./src
export BILIVE_CONFIG="${BILIVE_CONFIG:-$PROJECT_DIR/bilive-agent.toml}"
export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-/mnt/bilive/Videos}"
export BILIVE_LOG_DIR="${BILIVE_LOG_DIR:-/mnt/bilive/logs}"

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