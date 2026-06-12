"""Fail-closed dependency checks for the Windows slice worker."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

import requests
import toml

from src.db.conn import migrate_upload_queue


DependencyChecker = Callable[[dict[str, Any]], tuple[bool, str]]


def _load_config(project_root: Path) -> dict[str, Any]:
    config_path = Path(
        os.environ.get("BILIVE_CONFIG", project_root / "bilive-server.toml")
    )
    try:
        data = toml.load(config_path)
    except (OSError, toml.TomlDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _result(ready: bool, message: str) -> dict[str, str]:
    return {
        "status": "ready" if ready else "unavailable",
        "message": message,
    }


def _check_lm_studio(config: dict[str, Any]) -> tuple[bool, str]:
    provider = (
        config.get("slice", {}).get("llm_judge", {}).get("provider")
        or "openai-compatible"
    )
    if provider != "openai-compatible":
        return True, f"not required for provider {provider}"

    base_url = str(
        config.get("slice", {})
        .get("multi_modal", {})
        .get("visual_model_url", "http://127.0.0.1:1234/v1")
    ).rstrip("/")
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(f"{base_url}/models", timeout=3)
        response.raise_for_status()
    except requests.RequestException as exc:
        return False, str(exc)
    return True, f"{base_url}/models"


def _check_asr(config: dict[str, Any]) -> tuple[bool, str]:
    multi_modal = config.get("slice", {}).get("multi_modal", {})
    engine = str(multi_modal.get("whisper_engine", "faster-whisper"))
    if engine != "faster-whisper":
        return False, f"unsupported production ASR engine: {engine}"
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "faster-whisper is not installed"

    model = str(multi_modal.get("whisper_model", "large-v3"))
    model_path = Path(model).expanduser()
    if model_path.is_dir():
        return True, str(model_path.resolve())

    try:
        from huggingface_hub import snapshot_download

        repo_id = model if "/" in model else f"Systran/faster-whisper-{model}"
        cached = snapshot_download(repo_id=repo_id, local_files_only=True)
    except Exception as exc:
        return False, f"ASR model is not cached locally: {exc}"
    return True, str(cached)


def run_worker_preflight(
    *,
    project_root: str | Path,
    videos_root: str | Path,
    db_path: str | Path,
    lm_studio_checker: DependencyChecker = _check_lm_studio,
    asr_checker: DependencyChecker = _check_asr,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    videos = Path(videos_root).expanduser().resolve()
    database = Path(db_path).expanduser().resolve()
    config = _load_config(root)
    checks: dict[str, dict[str, str]] = {}

    videos_ready = videos.is_dir() and os.access(videos, os.R_OK | os.W_OK)
    checks["videos"] = _result(
        videos_ready,
        str(videos) if videos_ready else f"Videos directory is unavailable: {videos}",
    )

    database_ready = False
    database_message = str(database)
    try:
        migrate_upload_queue(database)
        with sqlite3.connect(database, timeout=5) as connection:
            connection.execute("select 1").fetchone()
        database_ready = True
    except (OSError, sqlite3.Error) as exc:
        database_message = str(exc)
    checks["database"] = _result(database_ready, database_message)

    lm_ready, lm_message = lm_studio_checker(config)
    checks["lm_studio"] = _result(lm_ready, lm_message)
    asr_ready, asr_message = asr_checker(config)
    checks["asr"] = _result(asr_ready, asr_message)

    unavailable = [
        name for name, check in checks.items() if check["status"] != "ready"
    ]
    return {
        "ready": not unavailable,
        "unavailable": unavailable,
        "checks": checks,
    }
