from pathlib import Path


PIPELINE_SCRIPT = Path("start_pipeline.ps1")
INSTALL_WORKER_TASK_SCRIPT = Path("install_windows_worker_task.ps1")
INSTALL_PI_SSH_KEY_SCRIPT = Path("install_windows_pi_ssh_key.ps1")
SETUP_WINDOWS_ENV_SCRIPT = Path("setup_windows_env.ps1")
START_PC_WORKER_API_SCRIPT = Path("start_pc_worker_api.ps1")
RUN_UPLOAD_SCRIPT = Path("run_upload.ps1")


def test_pipeline_launcher_starts_pc_worker_api():
    text = PIPELINE_SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$NoWorkerApi" not in text
    assert "BILIVE_CONFIG" in text
    assert "BILIVE_VIDEOS_DIR" in text
    assert "src.server.worker_api:api" in text
    assert '"--host", "127.0.0.1", "--port", "2235"' in text
    assert ".venv-win" in text
    assert "src.burn.scan_slice" not in text
    assert "RunLegacyScanSlice" not in text
    assert "[switch]$NoSlice" not in text
    assert '"-m", "src.upload.upload"' not in text
    assert 'BILIVE_DB_PATH' in text
    assert 'BILIVE_COOKIE_FILE' in text
    assert 'BILIVE_AUTO_UPLOAD' in text
    assert 'NO_PROXY' in text
    assert 'if ($NoUpload)' in text
    assert '& $python "-m" "uvicorn"' in text


def test_install_windows_worker_task_registers_logon_supervisor():
    text = INSTALL_WORKER_TASK_SCRIPT.read_text(encoding="utf-8")

    assert "BiliveWorkerApi" in text
    assert "start_pipeline.ps1" in text
    assert "Register-ScheduledTask" in text
    assert "New-ScheduledTaskAction" in text
    assert "New-ScheduledTaskSettingsSet" in text
    assert "New-ScheduledTaskTrigger -AtLogOn" in text
    assert "LogonType Interactive" in text
    assert "RunLevel Limited" in text
    assert "-WindowStyle Hidden" in text
    assert "BiliveSliceOnce" in text
    assert "Unregister-ScheduledTask" in text


def test_install_windows_pi_ssh_key_writes_admin_authorized_keys():
    text = INSTALL_PI_SSH_KEY_SCRIPT.read_text(encoding="utf-8")

    assert "administrators_authorized_keys" in text
    assert "pi-to-windows-bilive" in text
    assert "*S-1-5-32-544:F" in text
    assert "*S-1-5-18:F" in text


def test_duplicate_worker_and_upload_launchers_are_removed():
    assert not START_PC_WORKER_API_SCRIPT.exists()
    assert not RUN_UPLOAD_SCRIPT.exists()
    assert not Path("run_slice_once.ps1").exists()
    assert not Path("run_slice.ps1").exists()


def test_windows_environment_is_dedicated_and_pinned():
    text = SETUP_WINDOWS_ENV_SCRIPT.read_text(encoding="utf-8")
    requirements = Path("requirements/windows.txt").read_text(encoding="utf-8")

    assert ".venv-win" in text
    assert "requirements\\windows.txt" in text
    assert "-m pip check" in text
    assert "faster-whisper==" in requirements
    assert "openai==" in requirements
    assert "fastapi==" in requirements
    assert not Path("requirements.txt").exists()
