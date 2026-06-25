from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from src.server.worker_lock import default_worker_lock_path, read_worker_lock


_worker_process: subprocess.Popen | None = None
_worker_started_at: float = 0.0
_worker_command: list[str] = []
_worker_log_path: str = ""
_start_lock = threading.Lock()


def start_worker_once(
    project_root: str | Path | None = None,
    videos_root: str | Path | None = None,
) -> dict[str, Any]:
    """Start the PC-side pending worker once and return immediately."""
    global _worker_process, _worker_started_at, _worker_command, _worker_log_path

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    root = root.expanduser().resolve()
    videos = Path(videos_root) if videos_root is not None else Path(
        os.environ.get("BILIVE_VIDEOS_DIR", root / "Videos")
    )
    videos = videos.expanduser().resolve()
    lock_path = default_worker_lock_path(root)

    log_dir = root / "logs" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"pc-worker-{time.strftime('%Y%m%d-%H%M%S')}.log"
    command = [
        sys.executable,
        "-m",
        "src.server.watcher",
        "--once",
        "--videos-dir",
        str(videos),
        "--lock-file",
        str(lock_path),
    ]

    with _start_lock:
        if _worker_process is not None and _worker_process.poll() is None:
            return {"status": "already_running", "pid": _worker_process.pid}
        lock_status = read_worker_lock(lock_path)
        if lock_status["owner_running"]:
            return {"status": "already_running", "pid": lock_status["pid"]}

        with log_path.open("ab") as log_file:
            _worker_process = subprocess.Popen(
                command,
                cwd=str(root),
                env=_worker_environment(root, videos),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **_popen_options(),
            )

    _worker_started_at = time.time()
    _worker_command = command
    _worker_log_path = str(log_path)

    return {
        "status": "started",
        "pid": _worker_process.pid,
        "log_path": str(log_path),
        "videos_root": str(videos),
    }


def stop_worker(
    project_root: str | Path | None = None,
    videos_root: str | Path | None = None,
    *,
    lock_reader: Callable[[Path], dict[str, Any]] | None = None,
    terminator: Callable[[int], None] | None = None,
    recoverer: Callable[[Path], int] | None = None,
    pending_counter: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    """Stop the current one-shot worker and recover interrupted markers."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    root = root.expanduser().resolve()
    videos = Path(videos_root) if videos_root is not None else Path(
        os.environ.get("BILIVE_VIDEOS_DIR", root / "Videos")
    )
    videos = videos.expanduser().resolve()
    lock_path = default_worker_lock_path(root)
    read_lock = lock_reader or read_worker_lock
    stop_pid = terminator or _terminate_pid
    if recoverer is None:
        from src.server.watcher import recover_processing_markers

        recoverer = recover_processing_markers
    count_pending = pending_counter or _count_pending_markers

    pids: list[int] = []
    if _worker_process is not None and _worker_process.poll() is None:
        pids.append(int(_worker_process.pid))
    lock_status = read_lock(lock_path)
    try:
        lock_pid = int(lock_status.get("pid") or 0)
    except (TypeError, ValueError):
        lock_pid = 0
    if lock_pid > 0 and lock_status.get("owner_running"):
        pids.append(lock_pid)

    stopped: list[int] = []
    errors: list[str] = []
    for pid in dict.fromkeys(pids):
        try:
            stop_pid(pid)
            stopped.append(pid)
        except Exception as exc:  # pragma: no cover - OS boundary
            errors.append(f"{pid}: {exc}")

    recovered = int(recoverer(videos))
    result: dict[str, Any] = {
        "status": "stopped" if stopped else "idle",
        "stopped_pids": stopped,
        "recovered": recovered,
        "pending_tasks": int(count_pending(videos)),
        "log_path": _worker_log_path,
    }
    if errors:
        result["status"] = "partial"
        result["errors"] = errors
    return result


def _count_pending_markers(videos: Path) -> int:
    return len(list(videos.rglob("*.mp4.pending"))) if videos.is_dir() else 0


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(output or f"taskkill failed for PID {pid}")
        return
    os.kill(pid, signal.SIGTERM)


def worker_status() -> dict[str, Any]:
    if _worker_process is None:
        return {
            "status": "idle",
            "last_started_at": _worker_started_at,
            "last_command": _worker_command,
            "last_log_path": _worker_log_path,
        }
    return_code = _worker_process.poll()
    if return_code is None:
        return {
            "status": "running",
            "pid": _worker_process.pid,
            "started_at": _worker_started_at,
            "command": _worker_command,
            "log_path": _worker_log_path,
        }
    return {
        "status": "idle",
        "last_pid": _worker_process.pid,
        "last_returncode": return_code,
        "last_started_at": _worker_started_at,
        "last_command": _worker_command,
        "last_log_path": _worker_log_path,
    }


def _worker_environment(root: Path, videos: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["BILIVE_DIR"] = str(root)
    env["BILIVE_CONFIG"] = env.get("BILIVE_CONFIG", str(root / "bilive-server.toml"))
    env["BILIVE_VIDEOS_DIR"] = str(videos)
    env["PYTHONPATH"] = _prepend_pythonpath(
        [str(root), str(root / "src")],
        env.get("PYTHONPATH", ""),
    )
    return env


def _prepend_pythonpath(entries: list[str], existing: str) -> str:
    parts = [*entries]
    parts.extend(part for part in existing.split(os.pathsep) if part)
    return os.pathsep.join(dict.fromkeys(parts))


def _popen_options() -> dict[str, Any]:
    if os.name != "nt":
        return {"start_new_session": True}

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags}
