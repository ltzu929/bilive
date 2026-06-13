from pathlib import Path

from src.dashboard.remote_worker import (
    RemoteWorkerConfig,
    load_remote_worker_config,
    remote_worker_status,
    trigger_remote_worker,
)


def test_load_remote_worker_config_reads_toml_command(tmp_path):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashboard.remote_worker]",
                "enabled = true",
                'command = ["ssh", "win", "curl.exe", "-sS", "-X", "POST", "http://127.0.0.1:2235/api/worker/run-once"]',
                'status_command = ["ssh", "win", "curl.exe", "-sS", "http://127.0.0.1:2235/api/worker/status"]',
                "timeout = 8",
            ]
        ),
        encoding="utf-8",
    )

    config = load_remote_worker_config(config_path)

    assert config == RemoteWorkerConfig(
        enabled=True,
        command=[
            "ssh",
            "win",
            "curl.exe",
            "-sS",
            "-X",
            "POST",
            "http://127.0.0.1:2235/api/worker/run-once",
        ],
        status_command=[
            "ssh",
            "win",
            "curl.exe",
            "-sS",
            "http://127.0.0.1:2235/api/worker/status",
        ],
        timeout=8.0,
    )


def test_trigger_remote_worker_runs_configured_command():
    calls = []

    class Result:
        returncode = 0
        stdout = '{"status":"accepted","pid":1234}'
        stderr = ""

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    result = trigger_remote_worker(
        RemoteWorkerConfig(
            enabled=True,
            command=["ssh", "win", "curl.exe"],
            timeout=8,
        ),
        pending_tasks=2,
        runner=fake_runner,
    )

    assert result["status"] == "accepted"
    assert result["pid"] == 1234
    assert calls == [
        (
            ["ssh", "win", "curl.exe"],
            {"capture_output": True, "text": True, "timeout": 8},
        )
    ]


def test_trigger_remote_worker_skips_when_disabled():
    calls = []

    result = trigger_remote_worker(
        RemoteWorkerConfig(enabled=False, command=["ssh", "win"], timeout=8),
        pending_tasks=1,
        runner=lambda *args, **kwargs: calls.append(args),
    )

    assert result == {"status": "disabled", "message": "remote worker trigger is disabled"}
    assert calls == []


def test_trigger_remote_worker_reports_failed_command():
    class Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR: The system cannot find the file specified."

    result = trigger_remote_worker(
        RemoteWorkerConfig(enabled=True, command=["ssh", "win", "schtasks"], timeout=8),
        pending_tasks=1,
        runner=lambda *args, **kwargs: Result(),
    )

    assert result["status"] == "failed"
    assert result["returncode"] == 1
    assert "cannot find" in result["stderr"]


def test_trigger_remote_worker_skips_when_nothing_pending():
    result = trigger_remote_worker(
        RemoteWorkerConfig(enabled=True, command=["ssh", "win"], timeout=8),
        pending_tasks=0,
    )

    assert result == {"status": "skipped", "message": "no pending tasks"}


def test_remote_worker_status_reports_remote_mode_when_enabled():
    status = remote_worker_status(
        RemoteWorkerConfig(
            enabled=True,
            command=["ssh", "win", "curl.exe"],
            status_command=["ssh", "win", "curl.exe", "status"],
            timeout=10,
        ),
        runner=lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": '{"status":"idle","pending_tasks":0}',
                "stderr": "",
            },
        )(),
    )

    assert status["mode"] == "remote"
    assert status["enabled"] is True
    assert status["status"] == "idle"
    assert status["pending_tasks"] == 0


def test_remote_worker_status_reports_unavailable_when_disabled():
    status = remote_worker_status(
        RemoteWorkerConfig(enabled=False, command=[], status_command=[], timeout=10)
    )

    assert status == {
        "mode": "disabled",
        "enabled": False,
        "status": "unavailable",
        "message": "Remote Windows Worker API is disabled",
    }


def test_load_remote_worker_config_builds_commands_from_environment(tmp_path, monkeypatch):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashboard.remote_worker]",
                "enabled = true",
                "timeout = 8",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_WINDOWS_SSH_TARGET", "worker-host")

    config = load_remote_worker_config(config_path)

    assert config.command == [
        "ssh",
        "worker-host",
        "curl.exe",
        "-sS",
        "-X",
        "POST",
        "http://127.0.0.1:2235/api/worker/run-once",
    ]
    assert config.status_command[-1] == "http://127.0.0.1:2235/api/worker/status"
