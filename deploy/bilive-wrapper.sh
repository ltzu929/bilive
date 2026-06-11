#!/bin/bash
# Keep the Pi service alive while the Windows-hosted SMB share is offline.

set -u

PROJECT_DIR="${BILIVE_PROJECT_DIR:-/mnt/win/bilive}"
ENV_FILE="${BILIVE_ENV_FILE:-$PROJECT_DIR/.secrets/env}"
SETTINGS_FILE="${BILIVE_SETTINGS_FILE:-$PROJECT_DIR/settings.toml}"
PYTHON_BIN="${BILIVE_PYTHON_BIN:-/home/ubuntu/miniforge/envs/bilive/bin/python}"
SMB_HOST="${BILIVE_SMB_HOST:-192.168.31.202}"
SMB_PORT="${BILIVE_SMB_PORT:-445}"
WAIT_SECONDS="${BILIVE_WAIT_SECONDS:-15}"
HEALTHCHECK_SECONDS="${BILIVE_HEALTHCHECK_SECONDS:-15}"
RESTART_SECONDS="${BILIVE_RESTART_SECONDS:-10}"
PROBE_TIMEOUT_SECONDS="${BILIVE_PROBE_TIMEOUT_SECONDS:-5}"
CONNECT_TIMEOUT_SECONDS="${BILIVE_CONNECT_TIMEOUT_SECONDS:-3}"

export BILIVE_VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-$PROJECT_DIR/Videos}"
export BILIVE_LOG_DIR="${BILIVE_LOG_DIR:-$PROJECT_DIR/logs}"

BLREC_PID=""

log() {
    printf '%s %s\n' "$(date -Is)" "$*"
}

smb_ready() {
    timeout "$CONNECT_TIMEOUT_SECONDS" bash -c \
        "exec 3<>/dev/tcp/${SMB_HOST}/${SMB_PORT}" >/dev/null 2>&1
}

storage_ready() {
    smb_ready &&
        timeout "$PROBE_TIMEOUT_SECONDS" stat "$ENV_FILE" >/dev/null 2>&1 &&
        timeout "$PROBE_TIMEOUT_SECONDS" stat "$SETTINGS_FILE" >/dev/null 2>&1
}

stop_blrec() {
    if [ -n "$BLREC_PID" ] && kill -0 "$BLREC_PID" 2>/dev/null; then
        log "[INFO] Stopping blrec (PID $BLREC_PID)..."
        kill -TERM "$BLREC_PID" 2>/dev/null || true
        wait "$BLREC_PID" 2>/dev/null || true
    fi
    BLREC_PID=""
}

shutdown() {
    stop_blrec
    exit 0
}
trap shutdown INT TERM

while true; do
    if ! storage_ready; then
        log "[WAIT] Windows SMB share is unavailable; retrying in ${WAIT_SECONDS}s"
        sleep "$WAIT_SECONDS"
        continue
    fi

    unset RECORD_KEY
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    if [ -z "${RECORD_KEY:-}" ]; then
        log "[ERROR] RECORD_KEY is missing from $ENV_FILE; retrying in ${WAIT_SECONDS}s"
        sleep "$WAIT_SECONDS"
        continue
    fi

    if ! cd "$PROJECT_DIR" ||
        ! mkdir -p "$BILIVE_VIDEOS_DIR" "$BILIVE_LOG_DIR/record"; then
        log "[WAIT] Windows SMB share became unavailable during setup"
        sleep "$WAIT_SECONDS"
        continue
    fi

    BLREC_HOST="${BLREC_HOST:-0.0.0.0}"
    BLREC_PORT="${BLREC_PORT:-2233}"
    log "[INFO] Windows SMB share is ready; starting blrec on ${BLREC_HOST}:${BLREC_PORT}"

    "$PYTHON_BIN" -m blrec \
        --host "$BLREC_HOST" \
        --port "$BLREC_PORT" \
        -c "$SETTINGS_FILE" \
        --api-key "$RECORD_KEY" &
    BLREC_PID=$!

    while kill -0 "$BLREC_PID" 2>/dev/null; do
        sleep "$HEALTHCHECK_SECONDS"
        if ! storage_ready; then
            log "[WAIT] Windows SMB share was disconnected"
            stop_blrec
            break
        fi
    done

    if [ -n "$BLREC_PID" ]; then
        wait "$BLREC_PID"
        status=$?
        BLREC_PID=""
        log "[WARN] blrec exited with status $status; retrying in ${RESTART_SECONDS}s"
        sleep "$RESTART_SECONDS"
    else
        log "[WAIT] Waiting ${WAIT_SECONDS}s before checking the Windows SMB share"
        sleep "$WAIT_SECONDS"
    fi
done
