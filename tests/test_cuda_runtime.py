import os

from src.cuda_runtime import configure_cuda_dll_search_paths


def test_configure_cuda_dll_search_paths_is_idempotent(monkeypatch):
    import src.cuda_runtime as cuda_runtime

    monkeypatch.setattr(cuda_runtime, "_configured", False)
    monkeypatch.setattr(cuda_runtime, "_DLL_HANDLES", [])
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        cuda_runtime,
        "configure_cuda_dll_search_paths",
        cuda_runtime.configure_cuda_dll_search_paths,
    )

    first = configure_cuda_dll_search_paths()
    second = configure_cuda_dll_search_paths()

    assert isinstance(first, list)
    assert second == []
