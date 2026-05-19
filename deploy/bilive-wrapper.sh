#!/bin/bash
# bilive-wrapper.sh — systemd wrapper for blrec + scanner on Pi
# Manages both processes, forwards signals, exits when either dies.
#
# Environment variables (from /mnt/win/bilive/.secrets/env):
#   RECORD_KEY         — blrec API key (required)
#   BILIVE_COOKIE_FILE — cookie path (default: /mnt/win/bilive/.secrets/bilibili.cookie)
#   BLREC_HOST         — blrec listen address (default: 0.0.0.0)
#   BLREC_PORT         — blrec listen port (default: 2233)

set -e

PROJECT_DIR="/mnt/win/bilive"
cd "$PROJECT_DIR"

export BILIVE_VIDEOS_DIR="/mnt/win/bilive/Videos"
export BILIVE_LOG_DIR="/mnt/win/bilive/logs"
export PYTHONPATH="./src"

mkdir -p "$BILIVE_VIDEOS_DIR" "$BILIVE_LOG_DIR/record" "$BILIVE_LOG_DIR/runtime" "$BILIVE_LOG_DIR/scan"

# Validate RECORD_KEY
if [ -z "$RECORD_KEY" ]; then
    echo "[ERROR] RECORD_KEY not set. Add it to /mnt/win/bilive/.secrets/env"
    exit 1
fi

# Activate conda
CONDA_SH="$HOME/miniforge/etc/profile.d/conda.sh"
if [ ! -f "$CONDA_SH" ]; then
    echo "[ERROR] conda not found"
    exit 1
fi
source "$CONDA_SH" && conda activate bilive

# ── Cleanup: kill scanner when blrec exits ──
cleanup() {
    echo "[INFO] Stopping scanner (PID $SCANNER_PID)..."
    kill "$SCANNER_PID" 2>/dev/null || true
    wait "$SCANNER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Start scanner (background) ──
echo "[INFO] Starting scanner..."
python -m src.agent.scanner &
SCANNER_PID=$!

# ── Start blrec (foreground) ──
echo "[INFO] Starting blrec on port ${BLREC_PORT:-2233}..."

# Run blrec directly with full config
BLREC_HOST="${BLREC_HOST:-0.0.0.0}"
BLREC_PORT="${BLREC_PORT:-2233}"

exec python -m blrec \
    -c /mnt/win/bilive/settings.toml \
    --host "$BLREC_HOST" \
    --port "$BLREC_PORT" \
    --api-key "$RECORD_KEY" \
    --out-dir "$BILIVE_VIDEOS_DIR"