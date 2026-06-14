from pathlib import Path
import subprocess
import sys


SERVICE_FILE = Path("deploy/bilive-dashboard.service")
WRAPPER_FILE = Path("deploy/bilive-dashboard-wrapper.sh")


def test_dashboard_service_runs_low_write_dashboard_on_2234():
    text = SERVICE_FILE.read_text(encoding="utf-8")

    assert "After=network-online.target mnt-win.automount" in text
    assert "Requires=bilive.service" not in text
    assert "Wants=network-online.target mnt-win.automount bilive-smb-recover.timer" in text
    assert "Environment=PYTHONDONTWRITEBYTECODE=1" in text
    assert "Environment=BILIVE_VIDEOS_DIR=/mnt/win/bilive/Videos" in text
    assert "WorkingDirectory=/mnt/win/bilive" not in text
    assert "EnvironmentFile=-/mnt/win/bilive/.secrets/env" not in text
    assert "ExecStart=/usr/local/bin/bilive-dashboard-start.sh" in text
    assert "Restart=always" in text
    assert "MemoryMax=512M" in text
    assert "StandardOutput=null" in text
    assert "StandardError=journal" in text
    assert "--port 2234" not in text


def test_dashboard_wrapper_waits_for_smb_and_uses_local_python():
    text = WRAPPER_FILE.read_text(encoding="utf-8")

    assert 'PROJECT_DIR="${BILIVE_PROJECT_DIR:-/mnt/win/bilive}"' in text
    assert "storage_ready" in text
    assert "set -a" in text
    assert 'source "$PROJECT_DIR/.secrets/env"' in text
    assert "set +a" in text
    assert 'PYTHON_BIN="${BILIVE_PYTHON_BIN:-/home/ubuntu/miniforge/envs/bilive/bin/python}"' in text
    assert "-m uvicorn src.dashboard.app:api" in text
    assert "--host 0.0.0.0" in text
    assert "--port 2234" in text
    assert 'kill -TERM "$DASHBOARD_PID"' in text
    assert 'kill -KILL "$DASHBOARD_PID"' in text


def test_dashboard_import_does_not_load_windows_heavy_dependencies():
    script = """
import builtins
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    blocked = ("openai", "faster_whisper", "pysrt")
    if name in blocked or name.startswith(tuple(value + "." for value in blocked)):
        raise AssertionError(f"dashboard imported Windows dependency: {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import src.dashboard.app
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
