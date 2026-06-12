from __future__ import annotations

import json
import os
import shlex
import subprocess
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
    timeout: float = DEFAULT_TIMEOUT


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
    timeout = _as_timeout(
        os.environ.get("BILIVE_REMOTE_WORKER_TIMEOUT", section.get("timeout", DEFAULT_TIMEOUT))
    )

    return RemoteWorkerConfig(
        enabled=enabled,
        command=command,
        status_command=status_command,
        timeout=timeout,
    )


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

    try:
        completed = runner(
            cfg.command,
            capture_output=True,
            text=True,
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
        try:
            completed = runner(
                cfg.status_command,
                capture_output=True,
                text=True,
                timeout=cfg.timeout,
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
                "message": (completed.stderr or "").strip(),
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
    return {
        "mode": "disabled",
        "enabled": False,
        "status": "unavailable",
        "message": "Remote Windows Worker API is disabled",
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
