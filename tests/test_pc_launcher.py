from pathlib import Path


PIPELINE_SCRIPT = Path("start_pipeline.ps1")


def test_pipeline_launcher_starts_pc_worker_api():
    text = PIPELINE_SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$NoWorkerApi" in text
    assert "[switch]$RunLegacyScanSlice" in text
    assert "BILIVE_CONFIG" in text
    assert "BILIVE_VIDEOS_DIR" in text
    assert "src.server.worker_api:api" in text
    assert '"--host", "127.0.0.1", "--port", "2235"' in text
    assert "worker-api-$dateSuffix.log" in text
    assert "src.burn.scan_slice" in text
    assert "if ($RunLegacyScanSlice)" in text
