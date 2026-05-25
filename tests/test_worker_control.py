from src.server import worker_control


class RunningProcess:
    pid = 1234

    def poll(self):
        return None


def test_start_worker_once_spawns_one_shot_watcher(tmp_path, monkeypatch):
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

    videos = tmp_path / "Videos"
    monkeypatch.setattr(worker_control, "_worker_process", None)
    monkeypatch.setattr(worker_control.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(worker_control.sys, "executable", "python")

    result = worker_control.start_worker_once(project_root=tmp_path, videos_root=videos)

    assert result["status"] == "started"
    assert result["pid"] == 5678
    assert started["command"] == [
        "python",
        "-m",
        "src.server.watcher",
        "--once",
        "--videos-dir",
        str(videos),
    ]
    assert started["cwd"] == str(tmp_path)
    assert started["env"]["BILIVE_VIDEOS_DIR"] == str(videos)
    assert started["stdout_name"] == result["log_path"]


def test_start_worker_once_skips_duplicate_worker(monkeypatch):
    monkeypatch.setattr(worker_control, "_worker_process", RunningProcess())

    result = worker_control.start_worker_once()

    assert result == {"status": "already_running", "pid": 1234}


def test_worker_status_reports_idle(monkeypatch):
    monkeypatch.setattr(worker_control, "_worker_process", None)

    assert worker_control.worker_status() == {"status": "idle"}
