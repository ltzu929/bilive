from pathlib import Path

from src.dashboard.remote_worker import (
    RemoteWorkerConfig,
    load_remote_worker_config,
    remote_worker_status,
    trigger_remote_worker,
    wake_remote_worker,
)


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def test_stop_remote_worker_runs_configured_stop_command():
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result(returncode=0, stdout='{"status":"stopped","recovered":1}')

    from src.dashboard import remote_worker

    result = remote_worker.stop_remote_worker(
        RemoteWorkerConfig(
            enabled=True,
            stop_command=["ssh", "win", "curl.exe", "-X", "POST", "stop"],
            timeout=8,
        ),
        runner=fake_runner,
    )

    assert result["status"] == "stopped"
    assert result["recovered"] == 1
    assert calls[0][0] == ["ssh", "win", "curl.exe", "-X", "POST", "stop"]

def test_stop_remote_worker_uses_dedicated_stop_timeout():
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result(returncode=0, stdout='{"status":"idle"}')

    from src.dashboard import remote_worker

    result = remote_worker.stop_remote_worker(
        RemoteWorkerConfig(
            enabled=True,
            stop_command=["ssh", "win", "curl.exe", "-X", "POST", "stop"],
            timeout=8,
        ),
        runner=fake_runner,
    )

    assert result["status"] == "idle"
    assert calls[0][1]["timeout"] == 30


def test_load_remote_worker_config_reads_stop_timeout(tmp_path):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashboard.remote_worker]",
                "enabled = true",
                "timeout = 8",
                "stop_timeout = 45",
            ]
        ),
        encoding="utf-8",
    )

    config = load_remote_worker_config(config_path)

    assert config.timeout == 8
    assert config.stop_timeout == 45


def test_load_remote_worker_config_invalid_timeouts_use_field_defaults(tmp_path):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashboard.remote_worker]",
                "enabled = true",
                "timeout = 0",
                "stop_timeout = -5",
                "startup_timeout = \"bad\"",
                "poll_interval = 0",
            ]
        ),
        encoding="utf-8",
    )

    config = load_remote_worker_config(config_path)

    assert config.timeout == 10
    assert config.stop_timeout == 30
    assert config.startup_timeout == 30
    assert config.poll_interval == 1


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
            {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 8,
            },
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
    assert config.stop_command[-1] == "http://127.0.0.1:2235/api/worker/stop"
    assert config.wake_command == [
        "ssh",
        "worker-host",
        "schtasks.exe",
        "/Run",
        "/TN",
        "BiliveWorkerApi",
    ]


def test_load_remote_worker_config_reads_wake_settings(tmp_path, monkeypatch):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        "\n".join(
            [
                "[dashboard.remote_worker]",
                "enabled = true",
                "timeout = 8",
                "startup_timeout = 30",
                'task_name = "CustomWorkerTask"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_WINDOWS_SSH_TARGET", "worker-host")

    config = load_remote_worker_config(config_path)

    assert config.startup_timeout == 30
    assert config.wake_command[-4:] == [
        "schtasks.exe",
        "/Run",
        "/TN",
        "CustomWorkerTask",
    ]


def test_wake_remote_worker_starts_task_and_waits_until_ready():
    calls = []
    replies = iter(
        [
            Result(1, stderr="connection failed"),
            Result(0, stdout="SUCCESS"),
            Result(1, stderr="not ready"),
            Result(0, stdout='{"status":"idle","pending_tasks":0}'),
        ]
    )
    now = [0.0]

    def run(command, **_kwargs):
        calls.append(command)
        return next(replies)

    def sleep(seconds):
        now[0] += seconds

    config = RemoteWorkerConfig(
        enabled=True,
        command=["ssh", "win", "curl.exe", "run"],
        status_command=["ssh", "win", "curl.exe", "status"],
        wake_command=[
            "ssh",
            "win",
            "schtasks.exe",
            "/Run",
            "/TN",
            "BiliveWorkerApi",
        ],
        timeout=8,
        startup_timeout=30,
        poll_interval=1,
    )

    result = wake_remote_worker(
        config,
        runner=run,
        monotonic=lambda: now[0],
        sleeper=sleep,
    )

    assert result["status"] == "idle"
    assert calls[1][-4:] == [
        "schtasks.exe",
        "/Run",
        "/TN",
        "BiliveWorkerApi",
    ]
    assert calls.count(config.wake_command) == 1


def test_wake_remote_worker_does_not_start_task_when_api_is_ready():
    calls = []
    config = RemoteWorkerConfig(
        enabled=True,
        status_command=["ssh", "win", "curl.exe", "status"],
        wake_command=["ssh", "win", "schtasks.exe", "/Run"],
        timeout=8,
    )

    result = wake_remote_worker(
        config,
        runner=lambda command, **_kwargs: calls.append(command)
        or Result(0, stdout='{"status":"idle","pending_tasks":0}'),
    )

    assert result["status"] == "idle"
    assert calls == [config.status_command]


def test_wake_remote_worker_reports_startup_timeout():
    now = [0.0]
    config = RemoteWorkerConfig(
        enabled=True,
        status_command=["ssh", "win", "curl.exe", "status"],
        wake_command=["ssh", "win", "schtasks.exe", "/Run"],
        timeout=8,
        startup_timeout=2,
        poll_interval=1,
    )

    def run(command, **_kwargs):
        if command == config.wake_command:
            return Result(0, stdout="SUCCESS")
        return Result(1, stderr="not ready")

    def sleep(seconds):
        now[0] += seconds

    result = wake_remote_worker(
        config,
        runner=run,
        monotonic=lambda: now[0],
        sleeper=sleep,
    )

    assert result["status"] == "unavailable"
    assert "2" in result["message"]


def test_wake_remote_worker_decodes_windows_command_output_safely():
    calls = []
    config = RemoteWorkerConfig(
        enabled=True,
        status_command=["ssh", "win", "curl.exe", "status"],
        wake_command=["ssh", "win", "schtasks.exe", "/Run"],
        timeout=8,
    )

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command == config.status_command:
            return Result(0, stdout='{"status":"idle","pending_tasks":0}')
        return Result(0, stdout="成功")

    result = wake_remote_worker(config, runner=run)

    assert result["status"] == "idle"
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "replace"
