#!/bin/bash
# Start bilive dashboard on 2233 and keep blrec as a local recording engine.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
if [ -n "$git_common_dir" ]; then
    if [ "${git_common_dir#/}" = "$git_common_dir" ]; then
        git_common_dir="$PROJECT_DIR/$git_common_dir"
    fi
    MAIN_DIR="$(cd "$git_common_dir/.." && pwd)"
else
    MAIN_DIR="$PROJECT_DIR"
fi

RUNTIME_DIR="${BILIVE_RUNTIME_DIR:-$MAIN_DIR}"
VENV_DIR="${BILIVE_VENV_DIR:-$RUNTIME_DIR/venv}"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Python venv not found: $VENV_DIR"
    exit 1
fi
source "$VENV_DIR/bin/activate"
export PYTHONPATH=./src
export no_proxy=*
export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-$RUNTIME_DIR/Videos}"

if [ ${#RECORD_KEY} -lt 8 ] || [ ${#RECORD_KEY} -gt 80 ]; then
    echo "RECORD_KEY must be 8-80 characters. Set it before starting:"
    echo "  export RECORD_KEY=135879abC"
    exit 1
fi

mkdir -p "$RUNTIME_DIR/logs/record" ./logs/runtime

echo "Stopping existing bilive dashboard..."
dashboard_pids=$(ps aux | grep '[u]vicorn src.dashboard.app:api' | awk '{print $2}')
if [ -n "$dashboard_pids" ]; then
    kill -15 $dashboard_pids 2>/dev/null || true
    sleep 1
fi

echo "Starting blrec engine on 127.0.0.1:2234..."
BILIVE_RUNTIME_DIR="$RUNTIME_DIR" BILIVE_VENV_DIR="$VENV_DIR" BLREC_HOST=127.0.0.1 BLREC_PORT=2234 ./record.sh

echo "Starting bilive dashboard on 0.0.0.0:2233..."
echo "Videos: $BILIVE_VIDEOS_DIR"
nohup python -m uvicorn src.dashboard.app:api --host 0.0.0.0 --port 2233 > ./logs/runtime/dashboard-$(date +%Y%m%d-%H%M%S).log 2>&1 &
sleep 2

if python - <<'PY'
import socket

with socket.create_connection(("127.0.0.1", 2233), timeout=2):
    pass
PY
then
    echo "Success! bilive dashboard is running."
    echo "Dashboard: http://127.0.0.1:2233/tasks"
    echo "blrec engine: http://127.0.0.1:2234"
else
    echo "Failed to start bilive dashboard. Check logs/runtime for details."
    exit 1
fi
