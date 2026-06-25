import json
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


def test_stop_worker_terminates_watcher_and_lock_owner_then_recovers(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    videos.mkdir()
    stopped = []
    recovered = []

    class FakeProcess:
        pid = 100

        def poll(self):
            return None

    monkeypatch.setattr(worker_control, "_worker_process", FakeProcess())
    monkeypatch.setattr(worker_control, "_worker_log_path", "logs/runtime/pc-worker-test.log")

    result = worker_control.stop_worker(
        project_root=tmp_path,
        videos_root=videos,
        lock_reader=lambda _path: {
            "status": "locked",
            "pid": 200,
            "owner_running": True,
        },
        terminator=lambda pid: stopped.append(pid),
        recoverer=lambda path: recovered.append(path) or 1,
        pending_counter=lambda path: 4,
    )

    assert result == {
        "status": "stopped",
        "stopped_pids": [100, 200],
        "recovered": 1,
        "recovered_sources": 1,
        "recovered_actions": 0,
        "pending_tasks": 4,
        "log_path": "logs/runtime/pc-worker-test.log",
    }
    assert recovered == [videos]


def test_stop_worker_recovers_action_jobs_and_counts_all_pending(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260624-12-55-18.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    job_id = "a" * 32
    jobs = videos / ".bilive-jobs"
    jobs.mkdir()
    processing_job = jobs / f"{job_id}.processing.json"
    processing_job.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "action": "retry_judge",
                "segment_id": "segment-1",
                "status": "processing",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(worker_control, "_worker_process", None)
    monkeypatch.setattr(worker_control, "_worker_log_path", "")

    result = worker_control.stop_worker(
        project_root=tmp_path,
        videos_root=videos,
        lock_reader=lambda _path: {
            "status": "unlocked",
            "pid": None,
            "owner_running": False,
        },
    )

    assert result["status"] == "idle"
    assert result["recovered_sources"] == 0
    assert result["recovered_actions"] == 1
    assert result["recovered"] == 1
    assert result["pending_tasks"] == 2
    assert not processing_job.exists()
    assert (jobs / f"{job_id}.pending.json").exists()


def test_terminate_pid_kills_windows_process_tree(monkeypatch):
    calls = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(worker_control.os, "name", "nt")
    monkeypatch.setattr(worker_control.subprocess, "run", fake_run)

    worker_control._terminate_pid(4321)

    assert calls[0][0] == ["taskkill", "/PID", "4321", "/T", "/F"]