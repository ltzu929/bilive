#!/bin/bash
# Recover the Windows-backed CIFS mount after the SMB host returns online.

set -u

SMB_HOST="${BILIVE_SMB_HOST:-192.168.31.202}"
SMB_PORT="${BILIVE_SMB_PORT:-445}"
MOUNT_UNIT="${BILIVE_MOUNT_UNIT:-mnt-win.mount}"
MOUNT_POINT="${BILIVE_MOUNT_POINT:-/mnt/win}"
PROBE_PATH="${BILIVE_PROBE_PATH:-/mnt/win/bilive}"
BILIVE_SERVICE="${BILIVE_SERVICE:-bilive.service}"
CONNECT_TIMEOUT_SECONDS="${BILIVE_CONNECT_TIMEOUT_SECONDS:-3}"
PROBE_TIMEOUT_SECONDS="${BILIVE_PROBE_TIMEOUT_SECONDS:-5}"
STOP_TIMEOUT_SECONDS="${BILIVE_STOP_TIMEOUT_SECONDS:-15}"
MOUNT_TIMEOUT_SECONDS="${BILIVE_MOUNT_TIMEOUT_SECONDS:-35}"

log() {
    printf '%s %s\n' "$(date -Is)" "$*"
}

smb_ready() {
    timeout "$CONNECT_TIMEOUT_SECONDS" bash -c \
        "exec 3<>/dev/tcp/${SMB_HOST}/${SMB_PORT}" >/dev/null 2>&1
}

mount_healthy() {
    findmnt -rn -t cifs --target "$MOUNT_POINT" >/dev/null 2>&1 &&
        timeout "$PROBE_TIMEOUT_SECONDS" stat "$PROBE_PATH" >/dev/null 2>&1
}

if mount_healthy; then
    exit 0
fi

if ! smb_ready; then
    log "[WAIT] Windows SMB ${SMB_HOST}:${SMB_PORT} is offline"
    exit 0
fi

if findmnt -rn -t cifs --target "$MOUNT_POINT" >/dev/null 2>&1; then
    log "[WARN] CIFS mount is stale; stopping recorder before remount"
    timeout "$STOP_TIMEOUT_SECONDS" systemctl stop "$BILIVE_SERVICE" || true
    if ! timeout "$STOP_TIMEOUT_SECONDS" systemctl stop "$MOUNT_UNIT"; then
        log "[WARN] Normal unmount timed out; using lazy unmount"
        umount -l "$MOUNT_POINT" || true
    fi
fi

systemctl reset-failed "$MOUNT_UNIT" || true
if ! timeout "$MOUNT_TIMEOUT_SECONDS" systemctl start "$MOUNT_UNIT"; then
    log "[WARN] Failed to start $MOUNT_UNIT; retrying on the next timer tick"
    exit 0
fi

if ! mount_healthy; then
    log "[WARN] $MOUNT_UNIT started but $PROBE_PATH is not healthy"
    exit 0
fi

systemctl restart "$BILIVE_SERVICE"
log "[INFO] CIFS mount recovered; restarted $BILIVE_SERVICE"

