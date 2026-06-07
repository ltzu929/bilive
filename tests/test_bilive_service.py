from pathlib import Path


SERVICE_FILE = Path("deploy/bilive.service")
WRAPPER_FILE = Path("deploy/bilive-wrapper.sh")


def test_service_stays_active_while_windows_share_is_offline():
    text = SERVICE_FILE.read_text(encoding="utf-8")

    assert "EnvironmentFile=/mnt/win/bilive/.secrets/env" not in text
    assert "ExecStart=/usr/local/bin/bilive-start.sh" in text
    assert "Restart=always" in text
    assert "StandardOutput=journal" in text
    assert "StandardError=journal" in text


def test_wrapper_waits_for_share_and_stops_recorder_when_it_disappears():
    text = WRAPPER_FILE.read_text(encoding="utf-8")

    assert 'WAIT_SECONDS="${BILIVE_WAIT_SECONDS:-300}"' in text
    assert 'HEALTHCHECK_SECONDS="${BILIVE_HEALTHCHECK_SECONDS:-30}"' in text
    assert 'ENV_FILE="${BILIVE_ENV_FILE:-$PROJECT_DIR/.secrets/env}"' in text
    assert 'source "$ENV_FILE"' in text
    assert "storage_ready" in text
    assert 'kill -TERM "$BLREC_PID"' in text
    assert "python -m src.agent.scanner" not in text
