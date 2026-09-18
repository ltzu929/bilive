"""Windows CUDA DLL discovery shared by preflight and ASR."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_HANDLES: list[object] = []
_configured = False


def configure_cuda_dll_search_paths() -> list[str]:
    """Make venv-scoped NVIDIA DLLs visible to this process.

    Python 3.8+ does not use PATH for extension-module DLL resolution, so
    both PATH and os.add_dll_directory must be set in the process that
    actually loads ctranslate2/faster-whisper — not only in preflight.
    """
    global _configured
    if os.name != "nt":
        return []
    if _configured:
        return []

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    candidates = (
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cuda_nvrtc" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "ctranslate2",
    )
    existing_path = os.environ.get("PATH", "").split(os.pathsep)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    added: list[str] = []
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
            _DLL_HANDLES.append(add_dll_directory(directory))
        except OSError:
            continue
        added.append(directory)
    _configured = True
    return added
