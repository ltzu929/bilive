#!/bin/bash
# Start PC-side helper services for the dashboard workflow.
# Slicing is only started by pending jobs through the worker API.

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

pkill -f 'src.server.worker_api:api' 2>/dev/null || true
pkill -f 'src.upload.upload' 2>/dev/null || true

nohup python -m uvicorn src.server.worker_api:api --host 127.0.0.1 --port 2235 \
  > ./logs/runtime/worker-api-$(date +%Y%m%d-%H%M%S).log 2>&1 &

nohup python -m src.upload.upload \
  > ./logs/runtime/upload-$(date +%Y%m%d-%H%M%S).log 2>&1 &

echo "PC helpers started."
echo "  Config:      $BILIVE_CONFIG"
echo "  Videos:      $BILIVE_VIDEOS_DIR"
echo "  Worker API:  http://127.0.0.1:2235/api/worker/status"
echo "  Logs:        ./logs/runtime"
echo ""
echo "Queue slicing from the dashboard /tasks page."
