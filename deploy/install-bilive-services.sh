#!/bin/bash
# Install the Pi-local recorder and SMB recovery services.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${BILIVE_PROJECT_DIR:-/mnt/win/bilive}"
PYTHON_BIN="${BILIVE_PYTHON_BIN:-/home/ubuntu/miniforge/envs/bilive/bin/python}"
SETTINGS_FILE="${BILIVE_SETTINGS_FILE:-$PROJECT_DIR/settings.toml}"

"$PYTHON_BIN" -m pip install \
    --disable-pip-version-check \
    --requirement "$PROJECT_DIR/requirements/pi.txt"
"$PYTHON_BIN" -m pip install \
    --disable-pip-version-check \
    "$PROJECT_DIR/wheel/blrec-2.0.0b4-py3-none-any.whl"
"$PYTHON_BIN" -m pip uninstall --yes pydantic-settings sse-starlette
"$PYTHON_BIN" -m pip check

install -m 0755 "$SCRIPT_DIR/bilive-wrapper.sh" /usr/local/bin/bilive-start.sh
install -m 0755 \
    "$SCRIPT_DIR/bilive-dashboard-wrapper.sh" \
    /usr/local/bin/bilive-dashboard-start.sh
install -m 0755 "$SCRIPT_DIR/bilive-smb-recover.sh" /usr/local/sbin/bilive-smb-recover
install -m 0644 "$SCRIPT_DIR/bilive.service" /etc/systemd/system/bilive.service
install -m 0644 \
    "$SCRIPT_DIR/bilive-dashboard.service" \
    /etc/systemd/system/bilive-dashboard.service
install -m 0644 \
    "$SCRIPT_DIR/bilive-smb-recover.service" \
    /etc/systemd/system/bilive-smb-recover.service
install -m 0644 \
    "$SCRIPT_DIR/bilive-smb-recover.timer" \
    /etc/systemd/system/bilive-smb-recover.timer

PYTHONPATH="$PROJECT_DIR" "$PYTHON_BIN" -m src.blrec_patch
PYTHONPATH="$PROJECT_DIR" "$PYTHON_BIN" -m src.blrec_settings "$SETTINGS_FILE"

systemctl daemon-reload
systemctl enable bilive.service
systemctl enable bilive-dashboard.service
systemctl enable --now bilive-smb-recover.timer
systemctl start bilive-smb-recover.service
systemctl restart bilive.service
systemctl restart bilive-dashboard.service

systemctl --no-pager --full status \
    bilive-smb-recover.timer \
    bilive.service \
    bilive-dashboard.service
