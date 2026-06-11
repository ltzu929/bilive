#!/bin/bash
# Install the Pi-local recorder and SMB recovery services.

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    exec sudo "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

install -m 0755 "$SCRIPT_DIR/bilive-wrapper.sh" /usr/local/bin/bilive-start.sh
install -m 0755 "$SCRIPT_DIR/bilive-smb-recover.sh" /usr/local/sbin/bilive-smb-recover
install -m 0644 "$SCRIPT_DIR/bilive.service" /etc/systemd/system/bilive.service
install -m 0644 \
    "$SCRIPT_DIR/bilive-smb-recover.service" \
    /etc/systemd/system/bilive-smb-recover.service
install -m 0644 \
    "$SCRIPT_DIR/bilive-smb-recover.timer" \
    /etc/systemd/system/bilive-smb-recover.timer

systemctl daemon-reload
systemctl enable bilive.service
systemctl enable --now bilive-smb-recover.timer
systemctl start bilive-smb-recover.service
systemctl restart bilive.service

systemctl --no-pager --full status bilive-smb-recover.timer bilive.service

