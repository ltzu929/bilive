#!/bin/bash
# Keep the dashboard service alive while the Windows-hosted SMB share is offline.

set -u

PROJECT_DIR="${BILIVE_PROJECT_DIR:-/mnt/win/bilive}"
PYTHON_BIN="${BILIVE_PYTHON_BIN:-/home/ubuntu/miniforge/envs/bilive/bin/python}"
SMB_HOST="${BILIVE_SMB_HOST:-192.168.31.202}"
SMB_PORT="${BILIVE_SMB_PORT:-445}"
WAIT_SECONDS="${BILIVE_WAIT_SECONDS:-15}"
HEALTHCHECK_SECONDS="${BILIVE_HEALTHCHECK_SECONDS:-15}"
PROBE_TIMEOUT_SECONDS="${BILIVE_PROBE_TIMEOUT_SECONDS:-5}"
CONNECT_TIMEOUT_SECONDS="${BILIVE_CONNECT_TIMEOUT_SECONDS:-3}"
STOP_TIMEOUT_SECONDS="${BILIVE_STOP_TIMEOUT_SECONDS:-20}"

export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-$PROJECT_DIR/Videos}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"

DASHBOARD_PID=""

log() {
    printf '%s %s\n' "$(date -Is)" "$*"
}

smb_ready() {
    timeout "$CONNECT_TIMEOUT_SECONDS" bash -c \
        "exec 3<>/dev/tcp/${SMB_HOST}/${SMB_PORT}" >/dev/null 2>&1
}

storage_ready() {
    smb_ready &&
        timeout "$PROBE_TIMEOUT_SECONDS" stat "$PROJECT_DIR/src/dashboard/app.py" \
            >/dev/null 2>&1
}

stop_dashboard() {
    if [ -n "$DASHBOARD_PID" ] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        log "[INFO] Stopping dashboard (PID $DASHBOARD_PID)..."
        kill -TERM "$DASHBOARD_PID" 2>/dev/null || true
        elapsed=0
        while kill -0 "$DASHBOARD_PID" 2>/dev/null &&
            [ "$elapsed" -lt "$STOP_TIMEOUT_SECONDS" ]; do
            sleep 1
            elapsed=$((elapsed + 1))
        done
        if kill -0 "$DASHBOARD_PID" 2>/dev/null; then
            log "[WARN] Dashboard did not stop after ${STOP_TIMEOUT_SECONDS}s; killing it"
            kill -KILL "$DASHBOARD_PID" 2>/dev/null || true
        fi
        wait "$DASHBOARD_PID" 2>/dev/null || true
    fi
    DASHBOARD_PID=""
}

shutdown() {
    stop_dashboard
    exit 0
}
trap shutdown INT TERM

while true; do
    if ! storage_ready || ! cd "$PROJECT_DIR"; then
        log "[WAIT] Windows SMB share is unavailable; retrying in ${WAIT_SECONDS}s"
        sleep "$WAIT_SECONDS"
        continue
    fi

    if [ -f "$PROJECT_DIR/.secrets/env" ]; then
        # shellcheck disable=SC1091
        set -a
        source "$PROJECT_DIR/.secrets/env"
        set +a
    fi

    if ! "$PYTHON_BIN" -c \
        "from src.db.conn import migrate_upload_queue; migrate_upload_queue()"; then
        log "[WARN] Upload database migration failed; retrying in ${WAIT_SECONDS}s"
        sleep "$WAIT_SECONDS"
        continue
    fi

    log "[INFO] Starting bilive dashboard on 0.0.0.0:2234"
    "$PYTHON_BIN" -m uvicorn src.dashboard.app:api --host 0.0.0.0 --port 2234 &
    DASHBOARD_PID=$!

    while kill -0 "$DASHBOARD_PID" 2>/dev/null; do
        sleep "$HEALTHCHECK_SECONDS"
        if ! storage_ready; then
            log "[WAIT] Windows SMB share was disconnected"
            stop_dashboard
            break
        fi
    done

    if [ -n "$DASHBOARD_PID" ]; then
        wait "$DASHBOARD_PID"
        status=$?
        DASHBOARD_PID=""
        log "[WARN] Dashboard exited with status $status; retrying in ${WAIT_SECONDS}s"
    fi
    sleep "$WAIT_SECONDS"
done
