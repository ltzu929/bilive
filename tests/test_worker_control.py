from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
        "--lock-file",
        str(tmp_path / "logs" / "runtime" / "slice-worker.lock"),
    ]
    assert started["cwd"] == str(tmp_path)
    assert started["env"]["BILIVE_VIDEOS_DIR"] == str(videos)
    assert started["stdout_name"] == result["log_path"]


def test_start_worker_once_skips_duplicate_worker(monkeypatch):
    monkeypatch.setattr(worker_control, "_worker_process", RunningProcess())

    result = worker_control.start_worker_once()

    assert result == {"status": "already_running", "pid": 1234}


def test_concurrent_worker_starts_create_only_one_process(tmp_path, monkeypatch):
    starts = []
    barrier = Barrier(2)

    class FakePopen:
        pid = 5678

        def __init__(self, *_args, **_kwargs):
            starts.append(self.pid)

        def poll(self):
            return None

    videos = tmp_path / "Videos"
    monkeypatch.setattr(worker_control, "_worker_process", None)
    monkeypatch.setattr(worker_control.subprocess, "Popen", FakePopen)

    def start():
        barrier.wait()
        return worker_control.start_worker_once(
            project_root=tmp_path,
            videos_root=videos,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: start(), range(2)))

    assert starts == [5678]
    assert sorted(result["status"] for result in results) == [
        "already_running",
        "started",
    ]


def test_worker_status_reports_idle(monkeypatch):
    monkeypatch.setattr(worker_control, "_worker_process", None)
    monkeypatch.setattr(worker_control, "_worker_started_at", 0.0)
    monkeypatch.setattr(worker_control, "_worker_command", [])
    monkeypatch.setattr(worker_control, "_worker_log_path", "")

    status = worker_control.worker_status()
    assert status["status"] == "idle"
    assert "last_started_at" in status
    assert "last_command" in status
    assert "last_log_path" in status
