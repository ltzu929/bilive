import importlib
import json
import os
from pathlib import Path

import pytest


def _module():
    assert Path("src/server/worker_lock.py").exists(), "worker lock module is missing"
    return importlib.import_module("src.server.worker_lock")


def test_worker_process_lock_rejects_live_owner(tmp_path):
    worker_lock = _module()
    lock_path = tmp_path / "slice-worker.lock"
    with worker_lock.WorkerProcessLock(
        lock_path,
        pid=123,
        pid_checker=lambda pid: pid == 123,
    ):
        assert worker_lock.read_worker_lock(
            lock_path,
            pid_checker=lambda pid: pid == 123,
        ) == {
            "status": "locked",
            "pid": 123,
            "owner_running": True,
            "path": str(lock_path),
        }
        with pytest.raises(worker_lock.WorkerAlreadyRunning):
            with worker_lock.WorkerProcessLock(
                lock_path,
                pid=456,
                pid_checker=lambda pid: pid == 123,
            ):
                pass


def test_worker_process_lock_replaces_stale_owner(tmp_path):
    worker_lock = _module()
    lock_path = tmp_path / "slice-worker.lock"
    lock_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    with worker_lock.WorkerProcessLock(
        lock_path,
        pid=456,
        pid_checker=lambda _pid: False,
    ):
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == 456

    assert not lock_path.exists()


def test_worker_lock_status_does_not_trust_a_live_pid_without_kernel_lock(
    tmp_path,
):
    worker_lock = _module()
    lock_path = tmp_path / "slice-worker.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    status = worker_lock.read_worker_lock(lock_path)

    assert status["status"] == "unlocked"
    assert status["owner_running"] is False
