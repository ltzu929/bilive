# Copyright (c) 2024 bilive.
"""Cross-process lock for the single-instance upload consumer.

The lock is created with ``O_CREAT | O_EXCL`` and carries the owning PID so a
crashed previous owner can be detected and its stale lock reclaimed. This is
the upload-consumer analogue of ``src.server.worker_lock`` — a thread lock is
not sufficient because the worker may run as a separate process.
"""

from __future__ import annotations

import os
from pathlib import Path


class UploadAlreadyRunning(RuntimeError):
    pass


def _pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        error_access_denied = 5
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return kernel32.GetLastError() == error_access_denied

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class UploadProcessLock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._owned = False

    def __enter__(self) -> "UploadProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = self._create_lock()
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
        self._owned = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._owned:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._owned = False

    def _create_lock(self) -> int:
        try:
            return os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            if self._existing_owner_is_running():
                raise UploadAlreadyRunning(
                    f"upload consumer already owns {self.path}"
                ) from exc
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            try:
                return os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError as retry_exc:
                raise UploadAlreadyRunning(
                    f"upload consumer already owns {self.path}"
                ) from retry_exc

    def _existing_owner_is_running(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        if pid <= 0:
            return False
        return _pid_is_running(pid)