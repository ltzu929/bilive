import json

from src.server import upload_control


class RunningProcess:
    pid = 1234

    def poll(self):
        return None


def reset_upload_control(monkeypatch):
    monkeypatch.setattr(upload_control, "_upload_process", None)
    monkeypatch.setattr(upload_control, "_upload_started_at", 0.0)
    monkeypatch.setattr(upload_control, "_upload_command", [])
    monkeypatch.setattr(upload_control, "_upload_log_path", "")
    monkeypatch.setattr(upload_control, "_upload_status_path", "")


def test_start_upload_worker_spawns_long_running_consumer(tmp_path, monkeypatch):
    started = {}

    class FakePopen:
        pid = 5678

        def __init__(self, command, **kwargs):
            started["command"] = command
            started["cwd"] = kwargs["cwd"]
            started["env"] = kwargs["env"]
            started["stdout_name"] = kwargs["stdout"].name

        def poll(self):
            return None

    reset_upload_control(monkeypatch)
    monkeypatch.setattr(upload_control.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(upload_control.sys, "executable", "python")

    result = upload_control.start_upload_worker(
        project_root=tmp_path,
        videos_root=tmp_path / "Videos",
        db_path=tmp_path / "queue.db",
        cookie_file=tmp_path / ".secrets" / "bilibili.cookie",
    )

    assert result["status"] == "started"
    assert result["pid"] == 5678
    assert started["command"] == ["python", "-m", "src.upload.upload"]
    assert started["cwd"] == str(tmp_path)
    assert started["env"]["BILIVE_DIR"] == str(tmp_path)
    assert started["env"]["BILIVE_VIDEOS_DIR"] == str(tmp_path / "Videos")
    assert started["env"]["BILIVE_DB_PATH"] == str(tmp_path / "queue.db")
    assert started["env"]["BILIVE_COOKIE_FILE"] == str(
        tmp_path / ".secrets" / "bilibili.cookie"
    )
    assert started["env"]["BILIVE_UPLOAD_STATUS_FILE"] == result["status_path"]
    assert started["stdout_name"] == result["log_path"]


def test_start_upload_worker_skips_duplicate_process(monkeypatch):
    monkeypatch.setattr(upload_control, "_upload_process", RunningProcess())

    result = upload_control.start_upload_worker()

    assert result == {"status": "already_running", "pid": 1234}


def test_upload_worker_status_combines_process_and_status_file(
    tmp_path,
    monkeypatch,
):
    status_path = tmp_path / "upload-status.json"
    status_path.write_text(
        json.dumps(
            {
                "status": "paused_auth",
                "queue_counts": {"queued": 3, "total": 3},
                "error": "cookie expired",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(upload_control, "_upload_process", RunningProcess())
    monkeypatch.setattr(upload_control, "_upload_started_at", 100.0)
    monkeypatch.setattr(upload_control, "_upload_command", ["python", "-m", "src.upload.upload"])
    monkeypatch.setattr(upload_control, "_upload_log_path", "upload.log")
    monkeypatch.setattr(upload_control, "_upload_status_path", str(status_path))

    status = upload_control.upload_worker_status()

    assert status["process_status"] == "running"
    assert status["status"] == "paused_auth"
    assert status["queue_counts"]["queued"] == 3
    assert status["pid"] == 1234


def test_stop_upload_worker_terminates_owned_process(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 3456

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))
            return 0

    monkeypatch.setattr(upload_control, "_upload_process", FakeProcess())

    result = upload_control.stop_upload_worker()

    assert result == {"status": "stopped", "pid": 3456}
    assert calls == ["terminate", ("wait", 10)]
    assert upload_control._upload_process is None
