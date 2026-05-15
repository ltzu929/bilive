#!/bin/bash
# server.sh — 在 PC 上启动处理服务
#
# 用法:
#   ./server.sh                    # 使用默认配置
#   BILIVE_CONFIG=./bilive-server.toml ./server.sh  # 指定配置文件
#
# 环境变量:
#   BILIVE_CONFIG      — server 配置文件路径 (默认: ./bilive-server.toml)
#   BILIVE_VIDEOS_DIR  — 视频目录 (默认: ./Videos)
#   BILIVE_LOG_DIR     — 日志目录 (默认: ./logs)
#   BILIVE_DB_PATH     — 数据库路径 (默认: ./src/db/data.db)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

source venv/bin/activate
export PYTHONPATH=./src
export BILIVE_CONFIG="${BILIVE_CONFIG:-$PROJECT_DIR/bilive-server.toml}"

mkdir -p ./logs/runtime ./logs/scan ./logs/upload

# 停止旧进程
pkill -f 'src.server.watcher' 2>/dev/null || true
pkill -f 'src.upload.upload' 2>/dev/null || true

# 启动 watcher（监控 .pending 文件并处理）
nohup python -m src.server.watcher > ./logs/runtime/watcher-$(date +%Y%m%d-%H%M%S).log 2>&1 &

# 启动 upload worker
nohup python -m src.upload.upload > ./logs/runtime/upload-$(date +%Y%m%d-%H%M%S).log 2>&1 &

echo "Server started."
echo "  Config:    $BILIVE_CONFIG"
echo "  Logs:      ./logs/runtime"
echo ""
echo "Optional: Start dashboard with:"
echo "  python -m src.dashboard.app"