from pathlib import Path


SERVICE_FILE = Path("deploy/bilive-dashboard.service")


def test_dashboard_service_runs_low_write_dashboard_on_2234():
    text = SERVICE_FILE.read_text(encoding="utf-8")

    assert "After=network-online.target bilive.service" in text
    assert "Requires=bilive.service" in text
    assert "Environment=PYTHONDONTWRITEBYTECODE=1" in text
    assert "Environment=BILIVE_VIDEOS_DIR=/mnt/win/bilive/Videos" in text
    assert "ExecStart=/mnt/win/bilive/start_dashboard_pi.sh" in text
    assert "StandardOutput=null" in text
    assert "StandardError=journal" in text
    assert "--port 2234" not in text
