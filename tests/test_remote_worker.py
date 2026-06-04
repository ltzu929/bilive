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
                'command = ["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"]',
                "timeout = 8",
            ]
        ),
        encoding="utf-8",
    )

    config = load_remote_worker_config(config_path)

    assert config == RemoteWorkerConfig(
        enabled=True,
        command=["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"],
        timeout=8.0,
    )


def test_trigger_remote_worker_runs_configured_command():
    calls = []

    class Result:
        returncode = 0
        stdout = "SUCCESS: Attempted to run the scheduled task."
        stderr = ""

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    result = trigger_remote_worker(
        RemoteWorkerConfig(
            enabled=True,
            command=["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"],
            timeout=8,
        ),
        pending_tasks=2,
        runner=fake_runner,
    )

    assert result["status"] == "triggered"
    assert result["returncode"] == 0
    assert result["stdout"] == "SUCCESS: Attempted to run the scheduled task."
    assert calls == [
        (
            ["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"],
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
            command=["ssh", "zk@192.168.31.202", "schtasks", "/Run"],
            timeout=10,
        )
    )

    assert status == {
        "mode": "remote",
        "enabled": True,
        "message": "Pi remote Windows task trigger is enabled",
    }


def test_remote_worker_status_reports_local_fallback_when_disabled():
    status = remote_worker_status(
        RemoteWorkerConfig(enabled=False, command=[], timeout=10)
    )

    assert status == {
        "mode": "local",
        "enabled": False,
        "message": "Using browser-local PC worker API fallback",
    }
