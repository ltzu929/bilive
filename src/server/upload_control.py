from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


_upload_process: subprocess.Popen | None = None
_upload_started_at: float = 0.0
_upload_command: list[str] = []
_upload_log_path: str = ""
_upload_status_path: str = ""


def start_upload_worker(
    project_root: str | Path | None = None,
    videos_root: str | Path | None = None,
    db_path: str | Path | None = None,
    cookie_file: str | Path | None = None,
) -> dict[str, Any]:
    global _upload_process
    global _upload_started_at
    global _upload_command
    global _upload_log_path
    global _upload_status_path

    if _upload_process is not None and _upload_process.poll() is None:
        return {"status": "already_running", "pid": _upload_process.pid}

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    root = root.expanduser().resolve()
    videos = Path(videos_root) if videos_root is not None else Path(
        os.environ.get("BILIVE_VIDEOS_DIR", root / "Videos")
    )
    database = Path(db_path) if db_path is not None else Path(
        os.environ.get("BILIVE_DB_PATH", root / "src" / "db" / "data.db")
    )
    cookie = Path(cookie_file) if cookie_file is not None else Path(
        os.environ.get(
            "BILIVE_COOKIE_FILE",
            root / ".secrets" / "bilibili.cookie",
        )
    )
    videos = videos.expanduser().resolve()
    database = database.expanduser().resolve()
    cookie = cookie.expanduser().resolve()

    log_dir = root / "logs" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    suffix = time.strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"upload-process-{suffix}.log"
    status_path = log_dir / "upload-status.json"
    command = [sys.executable, "-m", "src.upload.upload"]
    environment = _upload_environment(
        root=root,
        videos=videos,
        database=database,
        cookie=cookie,
        status_path=status_path,
    )

    with log_path.open("ab") as log_file:
        _upload_process = subprocess.Popen(
            command,
            cwd=str(root),
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **_popen_options(),
        )

    _upload_started_at = time.time()
    _upload_command = command
    _upload_log_path = str(log_path)
    _upload_status_path = str(status_path)
    return {
        "status": "started",
        "pid": _upload_process.pid,
        "log_path": str(log_path),
        "status_path": str(status_path),
        "db_path": str(database),
        "cookie_file": str(cookie),
    }


def upload_worker_status() -> dict[str, Any]:
    process_status = "idle"
    process_data: dict[str, Any] = {
        "process_status": process_status,
        "last_started_at": _upload_started_at,
        "command": _upload_command,
        "log_path": _upload_log_path,
        "status_path": _upload_status_path,
    }
    if _upload_process is not None:
        return_code = _upload_process.poll()
        if return_code is None:
            process_status = "running"
            process_data.update(
                {
                    "process_status": process_status,
                    "pid": _upload_process.pid,
                    "started_at": _upload_started_at,
                }
            )
        else:
            process_data.update(
                {
                    "process_status": "idle",
                    "last_pid": _upload_process.pid,
                    "last_returncode": return_code,
                }
            )

    status_data = _read_status_file(_upload_status_path)
    if status_data:
        return {**process_data, **status_data, "process_status": process_status}
    return {**process_data, "status": process_status}


def stop_upload_worker(timeout: float = 10) -> dict[str, Any]:
    global _upload_process

    process = _upload_process
    if process is None or process.poll() is not None:
        _upload_process = None
        return {"status": "idle"}

    pid = process.pid
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
    _upload_process = None
    return {"status": "stopped", "pid": pid}


def _read_status_file(path_text: str) -> dict[str, Any] | None:
    if not path_text:
        return None
    try:
        data = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _upload_environment(
    *,
    root: Path,
    videos: Path,
    database: Path,
    cookie: Path,
    status_path: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env["BILIVE_DIR"] = str(root)
    env["BILIVE_CONFIG"] = env.get(
        "BILIVE_CONFIG",
        str(root / "bilive-server.toml"),
    )
    env["BILIVE_VIDEOS_DIR"] = str(videos)
    env["BILIVE_DB_PATH"] = str(database)
    env["BILIVE_COOKIE_FILE"] = str(cookie)
    env["BILIVE_UPLOAD_STATUS_FILE"] = str(status_path)
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
