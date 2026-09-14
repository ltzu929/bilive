"""Fail-closed dependency checks for the Windows slice worker."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import toml

DependencyChecker = Callable[[dict[str, Any]], tuple[bool, str]]
LLMChecker = Callable[[dict[str, Any], Path], tuple[bool, str]]

_CUDA_DLL_HANDLES: list[object] = []


def _configure_cuda_dll_search_paths() -> None:
    """Make the venv-scoped NVIDIA DLLs visible to this worker process.

    The NVIDIA runtime wheels install their DLLs below the Python environment,
    but a scheduled task does not inherit a PowerShell session's temporary
    PATH.  Keep the DLL-directory handles alive and also propagate the paths to
    child worker processes.
    """
    if os.name != "nt":
        return

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    candidates = (
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cuda_nvrtc" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "ctranslate2",
    )
    existing_path = os.environ.get("PATH", "").split(os.pathsep)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        directory = str(candidate.resolve())
        if directory not in existing_path:
            existing_path.insert(0, directory)
            os.environ["PATH"] = os.pathsep.join(existing_path)
        if add_dll_directory is None:
            continue
        try:
            _CUDA_DLL_HANDLES.append(add_dll_directory(directory))
        except OSError:
            continue


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


def _check_llm(
    config: dict[str, Any],
    project_root: Path,
) -> tuple[bool, str]:
    mimo = config.get("slice", {}).get("mimo", {})
    model = str(mimo.get("model", "mimo-v2.5"))
    if not os.environ.get("MIMO_API_KEY"):
        return False, "MIMO_API_KEY is not set"
    return True, f"MiMo API key configured for {model}"


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
        model_path = model_path.resolve()
    else:
        try:
            from huggingface_hub import snapshot_download

            repo_id = model if "/" in model else f"Systran/faster-whisper-{model}"
            cached = snapshot_download(repo_id=repo_id, local_files_only=True)
        except Exception as exc:
            return False, f"ASR model is not cached locally: {exc}"
        model_path = Path(cached).expanduser().resolve()

    device = str(multi_modal.get("whisper_device", "cpu")).strip().lower()
    if device not in {"cpu", "cuda"}:
        return False, f"unsupported ASR device: {device}"
    if device == "cuda":
        compute_type = str(
            multi_modal.get("whisper_compute_type", "float16")
        ).strip()
        try:
            cpu_threads = int(multi_modal.get("whisper_cpu_threads", 8))
        except (TypeError, ValueError):
            cpu_threads = 8
        return _check_cuda_asr_runtime(
            str(model_path),
            compute_type or "float16",
            max(1, cpu_threads),
        )
    return True, str(model_path)


@lru_cache(maxsize=8)
def _check_cuda_asr_runtime(
    model_path: str,
    compute_type: str,
    cpu_threads: int,
) -> tuple[bool, str]:
    """Validate CUDA and faster-whisper once before a worker claims work."""
    _configure_cuda_dll_search_paths()
    try:
        import ctranslate2
    except ImportError:
        return False, "ctranslate2 is not installed for CUDA ASR"

    try:
        device_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        return False, f"CUDA runtime is unavailable: {exc}"
    if device_count < 1:
        return False, "CUDA ASR requires at least one visible device"

    try:
        supported = ctranslate2.get_supported_compute_types("cuda")
    except Exception as exc:
        return False, f"CUDA compute types are unavailable: {exc}"
    if compute_type not in supported:
        return False, (
            f"CUDA compute type is unsupported: {compute_type}; "
            f"available={sorted(str(item) for item in supported)}"
        )

    try:
        from faster_whisper import WhisperModel
        import numpy as np

        model = WhisperModel(
            model_path,
            device="cuda",
            compute_type=compute_type,
            cpu_threads=max(1, int(cpu_threads)),
        )
        probe_audio = np.zeros(16000, dtype=np.float32)
        probe_segments, _probe_info = model.transcribe(
            probe_audio,
            language="zh",
            vad_filter=False,
            without_timestamps=True,
            beam_size=1,
            best_of=1,
        )
        list(probe_segments)
        del model
    except Exception as exc:
        return False, f"faster-whisper CUDA probe failed: {exc}"
    return True, (
        f"CUDA ASR ready: device_count={device_count}, "
        f"compute_type={compute_type}"
    )


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
