from pathlib import Path


SERVICE_FILE = Path("deploy/bilive.service")
WRAPPER_FILE = Path("deploy/bilive-wrapper.sh")
RECOVERY_SCRIPT = Path("deploy/bilive-smb-recover.sh")
RECOVERY_SERVICE = Path("deploy/bilive-smb-recover.service")
RECOVERY_TIMER = Path("deploy/bilive-smb-recover.timer")
INSTALLER = Path("deploy/install-bilive-services.sh")


def test_service_stays_active_while_windows_share_is_offline():
    text = SERVICE_FILE.read_text(encoding="utf-8")

    assert "EnvironmentFile=/mnt/win/bilive/.secrets/env" not in text
    assert "ExecStart=/usr/local/bin/bilive-start.sh" in text
    assert "Wants=network-online.target mnt-win.automount bilive-smb-recover.timer" in text
    assert "Environment=BILIVE_WAIT_SECONDS=15" in text
    assert "Environment=BILIVE_HEALTHCHECK_SECONDS=15" in text
    assert "TimeoutStopSec=30" in text
    assert "MemoryHigh=2500M" in text
    assert "MemoryMax=3200M" in text
    assert "Restart=always" in text
    assert "StandardOutput=journal" in text
    assert "StandardError=journal" in text


def test_wrapper_waits_for_share_and_stops_recorder_when_it_disappears():
    text = WRAPPER_FILE.read_text(encoding="utf-8")

    assert 'WAIT_SECONDS="${BILIVE_WAIT_SECONDS:-15}"' in text
    assert 'HEALTHCHECK_SECONDS="${BILIVE_HEALTHCHECK_SECONDS:-15}"' in text
    assert 'PROBE_TIMEOUT_SECONDS="${BILIVE_PROBE_TIMEOUT_SECONDS:-5}"' in text
    assert 'ENV_FILE="${BILIVE_ENV_FILE:-$PROJECT_DIR/.secrets/env}"' in text
    assert 'source "$ENV_FILE"' in text
    assert "storage_ready" in text
    assert 'kill -TERM "$BLREC_PID"' in text
    assert 'STOP_TIMEOUT_SECONDS="${BILIVE_STOP_TIMEOUT_SECONDS:-20}"' in text
    assert 'kill -KILL "$BLREC_PID"' in text
    assert 'VmRSS' in text
    assert 'export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "python -m src.agent.scanner" not in text


def test_recovery_timer_runs_root_oneshot_every_15_seconds():
    service = RECOVERY_SERVICE.read_text(encoding="utf-8")
    timer = RECOVERY_TIMER.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "User=" not in service
    assert "ExecStart=/usr/local/sbin/bilive-smb-recover" in service
    assert "OnBootSec=10s" in timer
    assert "OnUnitActiveSec=15s" in timer
    assert "WantedBy=timers.target" in timer


def test_recovery_script_repairs_failed_and_stale_cifs_mounts():
    text = RECOVERY_SCRIPT.read_text(encoding="utf-8")

    assert 'SMB_HOST="${BILIVE_SMB_HOST:-192.168.31.202}"' in text
    assert 'SMB_PORT="${BILIVE_SMB_PORT:-445}"' in text
    assert 'MOUNT_UNIT="${BILIVE_MOUNT_UNIT:-mnt-win.mount}"' in text
    assert 'PROBE_PATH="${BILIVE_PROBE_PATH:-/mnt/win/bilive}"' in text
    assert 'timeout "$CONNECT_TIMEOUT_SECONDS" bash -c' in text
    assert 'timeout "$PROBE_TIMEOUT_SECONDS" stat "$PROBE_PATH"' in text
    assert 'systemctl stop "$BILIVE_SERVICE"' in text
    assert 'systemctl stop "$DASHBOARD_SERVICE"' in text
    assert 'systemctl stop "$MOUNT_UNIT"' in text
    assert 'umount -l "$MOUNT_POINT"' in text
    assert 'systemctl reset-failed "$MOUNT_UNIT"' in text
    assert 'systemctl start "$MOUNT_UNIT"' in text
    assert 'systemctl restart "$BILIVE_SERVICE"' in text
    assert 'systemctl restart "$DASHBOARD_SERVICE"' in text


def test_installer_copies_local_recovery_units_and_enables_timer():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "/usr/local/bin/bilive-start.sh" in text
    assert "/usr/local/bin/bilive-dashboard-start.sh" in text
    assert "/usr/local/sbin/bilive-smb-recover" in text
    assert "/etc/systemd/system/bilive-smb-recover.service" in text
    assert "/etc/systemd/system/bilive-smb-recover.timer" in text
    assert "/etc/systemd/system/bilive-dashboard.service" in text
    assert "-m src.blrec_patch" in text
    assert "-m src.blrec_settings" in text
    assert 'requirements/pi.txt' in text
    assert '-m pip install' in text
    assert '-m pip check' in text
    assert "systemctl daemon-reload" in text
    assert "systemctl enable --now bilive-smb-recover.timer" in text
    assert "systemctl restart bilive.service" in text
    assert "systemctl restart bilive-dashboard.service" in text
