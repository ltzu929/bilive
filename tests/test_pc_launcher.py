from pathlib import Path


PIPELINE_SCRIPT = Path("start_pipeline.ps1")
RUN_SLICE_ONCE_SCRIPT = Path("run_slice_once.ps1")
INSTALL_SLICE_TASK_SCRIPT = Path("install_windows_slice_task.ps1")
INSTALL_PI_SSH_KEY_SCRIPT = Path("install_windows_pi_ssh_key.ps1")
START_PC_WORKER_API_SCRIPT = Path("start_pc_worker_api.ps1")
RUN_UPLOAD_SCRIPT = Path("run_upload.ps1")


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
    assert '"-m", "src.upload.upload"' not in text
    assert 'BILIVE_DB_PATH' in text
    assert 'BILIVE_COOKIE_FILE' in text
    assert 'BILIVE_AUTO_UPLOAD' in text
    assert 'if ($NoUpload)' in text


def test_run_slice_once_script_runs_watcher_synchronously_with_lock():
    text = RUN_SLICE_ONCE_SCRIPT.read_text(encoding="utf-8")

    assert "BILIVE_CONFIG" in text
    assert "BILIVE_VIDEOS_DIR" in text
    assert "slice-once.lock" in text
    assert "FileMode]::CreateNew" in text
    assert "src.server.watcher" in text
    assert "--once" in text
    assert "-Wait" in text
    assert "exit $proc.ExitCode" in text


def test_install_windows_slice_task_registers_manual_task():
    text = INSTALL_SLICE_TASK_SCRIPT.read_text(encoding="utf-8")

    assert "BiliveSliceOnce" in text
    assert "run_slice_once.ps1" in text
    assert "Register-ScheduledTask" in text
    assert "New-ScheduledTaskAction" in text
    assert "New-ScheduledTaskSettingsSet" in text
    assert "MultipleInstances IgnoreNew" in text
    assert "LogonType Interactive" in text
    assert "RunLevel Limited" in text
    assert "schtasks /Run /TN" in text


def test_install_windows_pi_ssh_key_writes_admin_authorized_keys():
    text = INSTALL_PI_SSH_KEY_SCRIPT.read_text(encoding="utf-8")

    assert "administrators_authorized_keys" in text
    assert "pi-to-windows-bilive" in text
    assert "*S-1-5-32-544:F" in text
    assert "*S-1-5-18:F" in text


def test_pc_worker_api_launcher_enables_managed_upload_paths():
    text = START_PC_WORKER_API_SCRIPT.read_text(encoding="utf-8")

    assert "BILIVE_CONFIG" in text
    assert "BILIVE_VIDEOS_DIR" in text
    assert "BILIVE_DB_PATH" in text
    assert "BILIVE_COOKIE_FILE" in text
    assert "src.server.worker_api:api" in text


def test_manual_upload_launcher_keeps_direct_consumer_entrypoint():
    text = RUN_UPLOAD_SCRIPT.read_text(encoding="utf-8")

    assert "BILIVE_CONFIG" in text
    assert "BILIVE_DB_PATH" in text
    assert "BILIVE_COOKIE_FILE" in text
    assert '"-m", "src.upload.upload"' in text
