"""Fail-closed dependency checks for the Windows slice worker."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

import requests
import toml

DependencyChecker = Callable[[dict[str, Any]], tuple[bool, str]]
LLMChecker = Callable[[dict[str, Any], Path], tuple[bool, str]]


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


def _configured_path(value: object, project_root: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _check_llm(
    config: dict[str, Any],
    project_root: Path,
) -> tuple[bool, str]:
    judge = config.get("slice", {}).get("llm_judge", {})
    provider = (
        judge.get("provider") or "openai-compatible"
    )
    if provider == "managed-llama-server":
        server = _configured_path(
            os.environ.get(
                "BILIVE_LLAMA_SERVER_PATH",
                judge.get("server_path", ""),
            ),
            project_root,
        )
        model = _configured_path(
            os.environ.get(
                "BILIVE_LLM_MODEL_PATH",
                judge.get("model_path", ""),
            ),
            project_root,
        )
        if not server.is_file():
            return False, f"managed llama-server is missing: {server}"
        if not model.is_file():
            return False, f"managed LLM model is missing: {model}"
        return True, f"managed runtime={server}; model={model}"
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
    llm_checker: LLMChecker = _check_llm,
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
        uri = f"file:{database.as_posix()}?mode=ro"
        with sqlite3.connect(uri, timeout=5, uri=True) as connection:
            version = int(connection.execute("pragma user_version").fetchone()[0])
            table = connection.execute(
                "select 1 from sqlite_master "
                "where type = 'table' and name = 'upload_queue'"
            ).fetchone()
        database_ready = version >= 1 and table is not None
        if not database_ready:
            database_message = "upload database schema is not initialized"
    except (OSError, sqlite3.Error) as exc:
        database_message = str(exc)
    checks["database"] = _result(database_ready, database_message)

    llm_ready, llm_message = llm_checker(config, root)
    checks["llm"] = _result(llm_ready, llm_message)
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
