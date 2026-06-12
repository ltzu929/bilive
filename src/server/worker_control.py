from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

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
