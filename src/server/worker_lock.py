"""Cross-process PID lock for the one-shot slice worker."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import BinaryIO, Callable


class WorkerAlreadyRunning(RuntimeError):
    pass


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        query_limited_information = 0x1000
        access_denied = 5
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(query_limited_information, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return kernel32.GetLastError() == access_denied

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def default_worker_lock_path(project_root: str | Path | None = None) -> Path:
    root = (
        Path(project_root)
        if project_root is not None
        else Path(os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2]))
    )
    return root.expanduser().resolve() / "logs" / "runtime" / "slice-worker.lock"


def _read_pid(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = int(data.get("pid") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return pid if pid > 0 else None


def _prepare_guard_file(path: Path) -> None:
    for _attempt in range(100):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if path.stat().st_size > 0:
                    return
            except FileNotFoundError:
                continue
            time.sleep(0.01)
            continue

        try:
            os.write(descriptor, b"\0")
        finally:
            os.close(descriptor)
        return
    raise OSError(f"could not initialize worker lock guard: {path}")


def _acquire_kernel_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_kernel_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _guard_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.guard")


def read_worker_lock(
    path: str | Path,
    *,
    pid_checker: Callable[[int], bool] = pid_is_running,
) -> dict:
    lock_path = Path(path)
    pid = _read_pid(lock_path)
    owner_running = False
    guard_path = _guard_path(lock_path)
    try:
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        _prepare_guard_file(guard_path)
        with guard_path.open("a+b", buffering=0) as handle:
            try:
                _acquire_kernel_lock(handle)
            except OSError:
                owner_running = True
            else:
                _release_kernel_lock(handle)
    except OSError:
        owner_running = bool(pid and pid_checker(pid))
    return {
        "status": "locked" if owner_running else "unlocked",
        "pid": pid,
        "owner_running": owner_running,
        "path": str(lock_path),
    }


class WorkerProcessLock:
    def __init__(
        self,
        path: str | Path,
        *,
        pid: int | None = None,
        pid_checker: Callable[[int], bool] = pid_is_running,
    ) -> None:
        self.path = Path(path)
        self.pid = int(pid or os.getpid())
        self.pid_checker = pid_checker
        self._owned = False
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "WorkerProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        guard_path = _guard_path(self.path)
        _prepare_guard_file(guard_path)
        handle = guard_path.open("r+b", buffering=0)
        try:
            _acquire_kernel_lock(handle)
        except OSError as exc:
            handle.close()
            owner = _read_pid(self.path)
            raise WorkerAlreadyRunning(
                f"slice worker PID {owner or 'unknown'} already owns {self.path}"
            ) from exc

        payload = json.dumps(
            {"pid": self.pid, "started_at": time.time()},
            ensure_ascii=True,
        ).encode("utf-8")
        temporary = self.path.with_name(f"{self.path.name}.{self.pid}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, self.path)
        self._handle = handle
        self._owned = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._owned:
            return
        handle = self._handle
        self._handle = None
        if handle is not None:
            try:
                if _read_pid(self.path) == self.pid:
                    self.path.unlink(missing_ok=True)
            finally:
                try:
                    _release_kernel_lock(handle)
                finally:
                    handle.close()
        self._owned = False
