#!/bin/bash
# Process the pending slice queue once.
# Daily slicing should queue jobs from the dashboard and use src.server.watcher.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

source venv/bin/activate
export PYTHONPATH="$PROJECT_DIR:$PROJECT_DIR/src"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export BILIVE_CONFIG="${BILIVE_CONFIG:-$PROJECT_DIR/bilive-server.toml}"
export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-$PROJECT_DIR/Videos}"

mkdir -p ./logs/runtime ./logs/scan ./logs/upload

python -m src.server.watcher --once --videos-dir "$BILIVE_VIDEOS_DIR"
