from pathlib import Path


PIPELINE_SCRIPT = Path("start_pipeline.ps1")
INSTALL_WORKER_TASK_SCRIPT = Path("install_windows_worker_task.ps1")
INSTALL_PI_SSH_KEY_SCRIPT = Path("install_windows_pi_ssh_key.ps1")
SETUP_WINDOWS_ENV_SCRIPT = Path("setup_windows_env.ps1")
SETUP_RECORDER_ENV_SCRIPT = Path("setup_windows_recorder_env.ps1")
START_WINDOWS_RECORDER_SCRIPT = Path("start_windows_recorder.ps1")
START_WINDOWS_DASHBOARD_SCRIPT = Path("start_windows_dashboard.ps1")
INSTALL_STARTUP_TASKS_SCRIPT = Path("install_windows_startup_tasks.ps1")
START_PC_WORKER_API_SCRIPT = Path("start_pc_worker_api.ps1")
RUN_UPLOAD_SCRIPT = Path("run_upload.ps1")
HEALTH_SCRIPT = Path("check_windows_health.ps1")
INSTALL_LLAMA_RUNTIME_SCRIPT = Path("install_llama_runtime.ps1")


def test_pipeline_launcher_starts_pc_worker_api():
    text = PIPELINE_SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$NoWorkerApi" not in text
    assert "src.server.worker_server" in text
    assert "src.server.worker_api:api" not in text
    assert ".venv-win" in text
    assert "src.burn.scan_slice" not in text
    assert "RunLegacyScanSlice" not in text
    assert "[switch]$NoSlice" not in text
    assert '"-m", "src.upload.upload"' not in text
    assert 'if ($NoUpload)' in text
    assert "LM Studio" not in text
    assert "BILIVE_LM_STUDIO_PATH" not in text
    assert '$ProjectDir;$ProjectDir\\src' not in text
    assert '"--console"' in text


def test_install_windows_worker_task_registers_on_demand_hidden_supervisor():
    text = INSTALL_WORKER_TASK_SCRIPT.read_text(encoding="utf-8")

    assert "BiliveWorkerApi" in text
    assert "start_pipeline.ps1" not in text
    assert "Register-ScheduledTask" in text
    assert "New-ScheduledTaskAction" in text
    assert "New-ScheduledTaskSettingsSet" in text
    assert "New-ScheduledTaskTrigger -AtLogOn" not in text
    assert "LogonType Interactive" in text
    assert "RunLevel Limited" in text
    assert "pythonw.exe" in text
    assert "-WorkingDirectory" in text
    assert "src.server.worker_server" in text
    assert "[switch]$NoUpload" in text
    assert "[switch]$EnableUpload" in text
    assert '" --no-upload"' in text
    assert "Invoke-RestMethod" in text
    assert "Get-NetTCPConnection" in text
    assert "Get-ScheduledTaskInfo" in text
    assert "Stop-ScheduledTask" in text
    assert "$portReleaseDeadline" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "Stop-Process" in text
    assert "src.server.worker_api:api" in text
    assert "$listenerBeforeStart" in text
    assert "$listener.OwningProcess -ne $listenerBeforeStart" in text
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
    assert "[switch]$Dev" in text
    assert "requirements\\dev.txt" in text
    assert "[switch]$InstallLlamaRuntime" in text
    assert "install_llama_runtime.ps1" in text
    assert "if ($InstallLlamaRuntime)" in text
    assert "[switch]$SkipLlamaRuntime" not in text
    assert "faster-whisper==" in requirements
    assert "openai==" in requirements
    assert "fastapi==" in requirements
    assert not Path("requirements.txt").exists()


def test_recorder_environment_is_separate_and_applies_blrec_hardening():
    text = SETUP_RECORDER_ENV_SCRIPT.read_text(encoding="utf-8")
    requirements = Path("requirements/recorder-windows.txt").read_text(
        encoding="utf-8"
    )

    assert ".venv-recorder" in text
    assert 'PythonVersion = "3.10"' in text
    assert "Get-Command uv" in text
    assert "requirements\\recorder-windows.txt" in text
    assert "src.blrec_patch" in text
    assert "src.blrec_settings" in text
    assert "settings.example.toml" in text
    assert "Copy-Item" in text
    assert "-m pip check" in text
    assert "blrec-2.0.0b4-py3-none-any.whl" in text
    assert "fastapi==0.88.0" in requirements
    assert "uvicorn[standard]==0.20.0" in requirements
    assert "setuptools==80.9.0" in requirements


def test_blrec_settings_supports_the_python_310_recorder_environment():
    source = Path("src/blrec_settings.py").read_text(encoding="utf-8")

    assert "except ModuleNotFoundError" in source
    assert "import toml as tomllib" in source
    assert "toml==0.10.2" in Path(
        "requirements/recorder-windows.txt"
    ).read_text(encoding="utf-8")


def test_windows_recorder_and_dashboard_launchers_are_local_only():
    recorder = START_WINDOWS_RECORDER_SCRIPT.read_text(encoding="utf-8")
    dashboard = START_WINDOWS_DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    assert ".venv-recorder" in recorder
    assert "src.server.recorder_server" in recorder
    assert '"--console"' in recorder
    assert 'HostAddress = "127.0.0.1"' in recorder
    assert "2233" in recorder

    assert ".venv-win" in dashboard
    assert "src.server.dashboard_server" in dashboard
    assert '"--console"' in dashboard
    assert 'HostAddress = "127.0.0.1"' in dashboard
    assert "2234" in dashboard


def test_windows_logon_tasks_use_current_interactive_user():
    text = INSTALL_STARTUP_TASKS_SCRIPT.read_text(encoding="utf-8")

    assert 'TaskName "BiliveRecorder"' in text
    assert 'TaskName "BiliveDashboard"' in text
    assert "New-ScheduledTaskTrigger -AtLogOn -User $UserId" in text
    assert "LogonType Interactive" in text
    assert "RunLevel Limited" in text
    assert "pythonw.exe" in text
    assert "src.server.recorder_server" in text
    assert "src.server.dashboard_server" in text
    assert "-WindowStyle Hidden" not in text
    assert "[switch]$NoRecorder" in text
    assert "if (-not $NoRecorder)" in text
    assert "SYSTEM" not in text


def test_windows_health_check_is_read_only_and_reports_all_dependencies():
    text = HEALTH_SCRIPT.read_text(encoding="utf-8")

    assert "Get-ScheduledTask" in text
    assert "Get-NetTCPConnection" in text
    assert "api/worker/status" in text
    assert "faster_whisper" in text
    assert "snapshot_download" in text
    assert "integrity_check" in text
    assert "upload.lock" in text
    assert "mimo" in text
    assert "MIMO_API_KEY" in text
    assert "Import-BiliveProjectEnv" in text
    assert ".secrets\\env" in text
    assert "managed_llm" not in text
    assert "lm_studio_port_1234" not in text
    assert '$env:PYTHONPATH = $ProjectDir' in text
    assert '$env:BILIVE_CONFIG' in text
    assert "Register-ScheduledTask" not in text
    assert "Start-ScheduledTask" not in text


def test_llama_runtime_installer_is_pinned_and_runtime_is_ignored():
    text = INSTALL_LLAMA_RUNTIME_SCRIPT.read_text(encoding="utf-8")
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert 'LlamaCppVersion = "b9616"' in text
    assert "llama-server.exe" in text
    assert "win-cuda-12" in text
    assert ".runtime/" in ignore


def test_mimo_runtime_is_documented_without_lm_studio_setup():
    readme = Path("README.md").read_text(encoding="utf-8")
    operations = Path("docs/operations.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    runtime = Path("docs/model-runtime.md").read_text(encoding="utf-8")
    public_docs = "\n".join([readme, operations, architecture, runtime])

    assert "BILIVE_LM_STUDIO_PATH" not in public_docs
    assert "MIMO_API_KEY" in public_docs
    assert r'Add-Content .\.secrets\env "MIMO_API_KEY=<your-key>"' not in public_docs
    assert "Set-BiliveSecret" in public_docs
    assert "mimo-v2.5" in public_docs
    assert "managed_runtime --smoke-test" not in public_docs
    assert "llama-server.exe" not in readme
    assert "2236" not in readme
    assert "pythonw.exe" in public_docs


def test_real_mimo_smoke_test_is_opt_in_and_never_uploads():
    smoke_test = Path("tests/integration/test_mimo_api_smoke.py")
    operations = Path("docs/operations.md").read_text(encoding="utf-8")

    assert smoke_test.exists()
    text = smoke_test.read_text(encoding="utf-8")
    assert "@pytest.mark.integration" in text
    assert "MIMO_API_KEY" in text
    assert "BILIVE_MIMO_SMOKE_VIDEO" in text
    assert "judge_candidate_with_mimo" in text
    assert "src.upload" not in text
    assert "upload_queue" not in text
    assert "tests\\integration\\test_mimo_api_smoke.py" in operations
    assert "-m integration" in operations
