from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import toml


DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class RemoteWorkerConfig:
    enabled: bool = False
    command: list[str] = field(default_factory=list)
    status_command: list[str] = field(default_factory=list)
    wake_command: list[str] = field(default_factory=list)
    timeout: float = DEFAULT_TIMEOUT
    startup_timeout: float = 30.0
    poll_interval: float = 1.0


def load_remote_worker_config(config_path: str | Path | None = None) -> RemoteWorkerConfig:
    path = Path(config_path) if config_path is not None else _default_config_path()
    data = _load_toml(path)
    section = data.get("dashboard", {}).get("remote_worker", {})

    enabled = _as_bool(
        os.environ.get("BILIVE_REMOTE_WORKER_ENABLED"),
        bool(section.get("enabled", False)),
    )
    command = _command_from_value(
        os.environ.get("BILIVE_REMOTE_WORKER_COMMAND", section.get("command", []))
    )
    status_command = _command_from_value(
        os.environ.get(
            "BILIVE_REMOTE_WORKER_STATUS_COMMAND",
            section.get("status_command", []),
        )
    )
    wake_command = _command_from_value(
        os.environ.get(
            "BILIVE_REMOTE_WORKER_WAKE_COMMAND",
            section.get("wake_command", []),
        )
    )
    timeout = _as_timeout(
        os.environ.get("BILIVE_REMOTE_WORKER_TIMEOUT", section.get("timeout", DEFAULT_TIMEOUT))
    )
    startup_timeout = _as_timeout(
        os.environ.get(
            "BILIVE_REMOTE_WORKER_STARTUP_TIMEOUT",
            section.get("startup_timeout", 30),
        )
    )
    poll_interval = _as_timeout(section.get("poll_interval", 1))
    task_name = str(
        os.environ.get(
            "BILIVE_WINDOWS_WORKER_TASK",
            section.get("task_name", "BiliveWorkerApi"),
        )
    ).strip()
    target = str(
        os.environ.get(
            "BILIVE_WINDOWS_SSH_TARGET",
            section.get("target", ""),
        )
    ).strip()
    if target and not command:
        command = [
            "ssh",
            target,
            "curl.exe",
            "-sS",
            "-X",
            "POST",
            "http://127.0.0.1:2235/api/worker/run-once",
        ]
    if target and not status_command:
        status_command = [
            "ssh",
            target,
            "curl.exe",
            "-sS",
            "http://127.0.0.1:2235/api/worker/status",
        ]
    if target and task_name and not wake_command:
        wake_command = [
            "ssh",
            target,
            "schtasks.exe",
            "/Run",
            "/TN",
            task_name,
        ]

    return RemoteWorkerConfig(
        enabled=enabled,
        command=command,
        status_command=status_command,
        wake_command=wake_command,
        timeout=timeout,
        startup_timeout=startup_timeout,
        poll_interval=poll_interval,
    )


def wake_remote_worker(
    config: RemoteWorkerConfig | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    cfg = config or load_remote_worker_config()
    if not cfg.enabled:
        return {
            "mode": "disabled",
            "enabled": False,
            "status": "unavailable",
            "message": "Remote Windows Worker API is disabled",
        }
    if not cfg.status_command:
        return {
            "mode": "remote",
            "enabled": True,
            "status": "unavailable",
            "message": "Remote worker status command is empty",
        }

    current = _read_remote_status(cfg, runner)
    if current.get("status") != "unavailable":
        return current
    if not cfg.wake_command:
        return {
            **current,
            "message": "Remote worker wake command is empty",
        }

    try:
        started = runner(
            cfg.wake_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "mode": "remote",
            "enabled": True,
            "status": "unavailable",
            "message": str(exc),
        }
    if started.returncode != 0:
        return {
            "mode": "remote",
            "enabled": True,
            "status": "unavailable",
            "message": (started.stderr or started.stdout or "").strip(),
        }

    deadline = monotonic() + cfg.startup_timeout
    while monotonic() < deadline:
        sleeper(cfg.poll_interval)
        current = _read_remote_status(cfg, runner)
        if current.get("status") != "unavailable":
            return current
    return {
        "mode": "remote",
        "enabled": True,
        "status": "unavailable",
        "message": (
            f"Windows Worker API did not start within "
            f"{cfg.startup_timeout:g}s"
        ),
    }


def trigger_remote_worker(
    config: RemoteWorkerConfig | None = None,
    pending_tasks: int = 0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if pending_tasks <= 0:
        return {"status": "skipped", "message": "no pending tasks"}

    cfg = config or load_remote_worker_config()
    if not cfg.enabled:
        return {"status": "disabled", "message": "remote worker trigger is disabled"}
    if not cfg.command:
        return {"status": "disabled", "message": "remote worker command is empty"}
    if cfg.wake_command and cfg.status_command:
        wake = wake_remote_worker(config=cfg, runner=runner)
        if wake.get("status") == "unavailable":
            return {
                "status": "failed",
                "message": wake.get("message") or "Windows Worker API is unavailable",
            }

    try:
        completed = runner(
            cfg.command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "message": f"remote worker trigger timed out after {cfg.timeout:g}s",
            "command": cfg.command,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    except OSError as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "command": cfg.command,
            "stdout": "",
            "stderr": "",
        }

    if completed.returncode != 0:
        return {
            "status": "failed",
            "returncode": completed.returncode,
            "command": cfg.command,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }

    try:
        payload = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "message": "Windows worker API returned invalid JSON",
        }
    return {
        **payload,
        "returncode": completed.returncode,
        "command": cfg.command,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
    }


def remote_worker_status(
    config: RemoteWorkerConfig | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    cfg = config or load_remote_worker_config()
    if cfg.enabled and cfg.status_command:
        return _read_remote_status(cfg, runner)
    return {
        "mode": "disabled",
        "enabled": False,
        "status": "unavailable",
        "message": "Remote Windows Worker API is disabled",
    }


def _read_remote_status(
    config: RemoteWorkerConfig,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        completed = runner(
            config.status_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "mode": "remote",
            "enabled": True,
            "status": "unavailable",
            "message": str(exc),
        }
    if completed.returncode != 0:
        return {
            "mode": "remote",
            "enabled": True,
            "status": "unavailable",
            "message": (completed.stderr or completed.stdout or "").strip(),
        }
    try:
        payload = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError:
        payload = {
            "status": "unavailable",
            "message": "Windows worker API returned invalid JSON",
        }
    return {
        **payload,
        "mode": "remote",
        "enabled": True,
        "message": payload.get("message") or "Windows Worker API",
    }


def _default_config_path() -> Path:
    env_path = os.environ.get("BILIVE_CONFIG")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[2] / "bilive-server.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = toml.load(path)
    except toml.TomlDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _command_from_value(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return shlex.split(raw)
    if isinstance(raw, list):
        return [str(part) for part in raw if str(part)]
    return []


def _as_timeout(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT
