from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests
import toml

from src.db.conn import (
    UPLOAD_STATUSES,
    claim_next_upload,
    defer_upload_for_auth,
    get_upload_queue_counts,
    list_upload_queue,
    mark_upload_complete,
    mark_upload_failed,
    mark_upload_published,
    migrate_upload_queue,
    peek_next_upload,
    recover_upload_queue,
    schedule_upload_retry,
)
from src.upload.bilibili_web import BilibiliWebClient
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    read_slice_upload_metadata,
    slice_upload_metadata_path,
)


class UploadAlreadyRunning(RuntimeError):
    pass


class UploadMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class UploadSettings:
    db_path: Path
    cookie_file: Path
    status_file: Path
    lock_file: Path
    poll_interval_seconds: float = 10
    max_attempts: int = 3
    retry_base_seconds: float = 30
    auth_retry_seconds: float = 120
    delete_after_success: bool = True
    upload_line: str = "auto"
    tid: int = 138
    sensitive_values: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        object.__setattr__(self, "cookie_file", Path(self.cookie_file))
        object.__setattr__(self, "status_file", Path(self.status_file))
        object.__setattr__(self, "lock_file", Path(self.lock_file))


@dataclass(frozen=True)
class UploadResult:
    status: str
    video_path: str = ""
    bvid: str = ""
    error: str = ""
    next_attempt_at: float = 0


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


def parse_cookie_file(path: str | Path) -> dict[str, str]:
    cookie_path = Path(path)
    text = cookie_path.read_text(encoding="utf-8").strip()
    cookies: dict[str, str] = {}
    for item in text.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key:
            cookies[key.strip()] = value.strip()
    missing = [name for name in ("SESSDATA", "bili_jct") if not cookies.get(name)]
    if missing:
        raise ValueError(f"missing Bilibili cookies: {', '.join(missing)}")
    return cookies


class BilibiliRuntimeClient:
    def __init__(
        self,
        *,
        cookies: dict[str, str],
        upload_line: str = "auto",
        session: requests.Session | None = None,
    ) -> None:
        self.cookies = dict(cookies)
        self.upload_line = upload_line
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/143.0.0.0 Safari/537.36"
                ),
                "Referer": "https://member.bilibili.com/",
            }
        )
        self.session.cookies.update(self.cookies)
        self.web = BilibiliWebClient(
            session=self.session,
            csrf=self.cookies["bili_jct"],
        )

    def check_login(self) -> dict[str, Any] | None:
        response = self.session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("isLogin") is not True:
            return None
        return {
            "isLogin": True,
            "uname": str(data.get("uname") or ""),
            "mid": data.get("mid"),
        }

    def upload_file(
        self,
        video_path: str,
        metadata: dict[str, Any],
    ) -> str:
        from src.upload.bilitool.bilitool.controller.upload_controller import (
            UploadController,
        )

        controller = UploadController()
        controller.bili_uploader.session = self.session
        headers = dict(self.session.headers)
        headers["Cookie"] = "; ".join(
            f"{key}={value}" for key, value in self.cookies.items()
        )
        controller.bili_uploader.headers = headers
        remote_filename = controller.upload_video(
            video_path,
            cdn=self.upload_line,
        )
        if not remote_filename:
            raise RuntimeError("UPOS upload did not return a remote filename")
        return str(remote_filename)

    def submit_uploaded_video(
        self,
        remote_filename: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.web.submit_uploaded_video(remote_filename, metadata)


class UploadWorker:
    def __init__(self, settings: UploadSettings, client) -> None:
        self.settings = settings
        self.client = client

    def process_one(self, *, now: float | None = None) -> UploadResult:
        current_time = time.time() if now is None else float(now)
        pending = peek_next_upload(self.settings.db_path, now=current_time)
        if pending is None:
            return self._finish(UploadResult(status="idle"))

        video_path = str(pending["video_path"])
        try:
            metadata = self._load_metadata(video_path)
        except (OSError, UploadMetadataError, ValueError) as exc:
            error = self._sanitize_error(exc)
            mark_upload_failed(
                video_path,
                error,
                db_path=self.settings.db_path,
                now=current_time,
            )
            return self._finish(
                UploadResult(
                    status="failed",
                    video_path=video_path,
                    error=error,
                )
            )

        try:
            login = self.client.check_login()
        except Exception as exc:
            error = self._sanitize_error(exc)
            return self._finish(
                UploadResult(
                    status="paused_auth",
                    video_path=video_path,
                    error=error,
                    next_attempt_at=current_time
                    + self.settings.auth_retry_seconds,
                )
            )
        if not login:
            return self._finish(
                UploadResult(
                    status="paused_auth",
                    video_path=video_path,
                    error="Bilibili cookie is not logged in",
                    next_attempt_at=current_time
                    + self.settings.auth_retry_seconds,
                )
            )

        item = claim_next_upload(self.settings.db_path, now=current_time)
        if item is None:
            return self._finish(UploadResult(status="idle"))
        video_path = str(item["video_path"])

        try:
            if item["status"] == "uploading":
                remote_filename = self.client.upload_file(video_path, metadata)
                mark_upload_complete(
                    video_path,
                    remote_filename,
                    db_path=self.settings.db_path,
                    now=current_time,
                )
                item = claim_next_upload(
                    self.settings.db_path,
                    now=current_time,
                )
                if item is None or str(item["video_path"]) != video_path:
                    raise RuntimeError(
                        "uploaded item could not transition to publishing"
                    )
            remote_filename = str(item["remote_filename"])
            response = self.client.submit_uploaded_video(
                remote_filename,
                metadata,
            )
            code = int(response.get("code", -1))
            if code != 0:
                message = str(response.get("message") or f"Bilibili API code {code}")
                return self._retry(
                    video_path,
                    f"Bilibili API {code}: {message}",
                    current_time,
                    paused_auth=code in {-101, -111},
                )

            data = response.get("data")
            bvid = str(data.get("bvid") or "") if isinstance(data, dict) else ""
            if not bvid:
                return self._retry(
                    video_path,
                    "Bilibili submission succeeded without a BVID",
                    current_time,
                )

            mark_upload_published(
                video_path,
                bvid,
                db_path=self.settings.db_path,
                now=current_time,
            )
            cleanup_error = ""
            if self.settings.delete_after_success:
                try:
                    self._cleanup(video_path, metadata)
                except Exception as exc:
                    cleanup_error = self._sanitize_error(exc)
            return self._finish(
                UploadResult(
                    status="published",
                    video_path=video_path,
                    bvid=bvid,
                    error=cleanup_error,
                )
            )
        except Exception as exc:
            return self._retry(
                video_path,
                self._sanitize_error(exc),
                current_time,
            )

    def _load_metadata(self, video_path: str) -> dict[str, Any]:
        path = Path(video_path)
        if not path.is_file():
            raise UploadMetadataError(f"video file does not exist: {path}")

        sidecar = slice_upload_metadata_path(path)
        if not sidecar.is_file():
            raise UploadMetadataError(f"upload metadata does not exist: {sidecar}")
        metadata = read_slice_upload_metadata(path)
        if metadata is None:
            raise UploadMetadataError(f"upload metadata is invalid: {sidecar}")

        title = str(metadata.get("title") or "").strip()
        if not title:
            raise UploadMetadataError(f"upload metadata title is empty: {sidecar}")
        tag = metadata.get("tag") or "直播切片"
        if isinstance(tag, list):
            tag = ",".join(str(value) for value in tag if str(value).strip())
        return {
            "title": title,
            "desc": str(metadata.get("desc") or ""),
            "tid": self.settings.tid,
            "tag": str(tag),
            "source": str(
                metadata.get("source") or "https://live.bilibili.com/"
            ),
            "cover": str(metadata.get("cover") or ""),
            "dynamic": str(metadata.get("dynamic") or ""),
            "copyright": 2,
        }

    def _retry(
        self,
        video_path: str,
        error: str,
        now: float,
        *,
        paused_auth: bool = False,
    ) -> UploadResult:
        sanitized = self._sanitize_error(error)
        if paused_auth:
            next_attempt_at = now + self.settings.auth_retry_seconds
            defer_upload_for_auth(
                video_path,
                sanitized,
                retry_at=next_attempt_at,
                db_path=self.settings.db_path,
                now=now,
            )
            return self._finish(
                UploadResult(
                    status="paused_auth",
                    video_path=video_path,
                    error=sanitized,
                    next_attempt_at=next_attempt_at,
                )
            )

        item = schedule_upload_retry(
            video_path,
            sanitized,
            max_attempts=self.settings.max_attempts,
            retry_base_seconds=self.settings.retry_base_seconds,
            db_path=self.settings.db_path,
            now=now,
        )
        if item is None or item["status"] == "failed":
            return self._finish(
                UploadResult(
                    status="failed",
                    video_path=video_path,
                    error=sanitized,
                )
            )
        return self._finish(
            UploadResult(
                status="retry",
                video_path=video_path,
                error=sanitized,
                next_attempt_at=float(item["next_attempt_at"] or 0),
            )
        )

    def _cleanup(self, video_path: str, metadata: dict[str, Any]) -> None:
        path = Path(video_path)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        delete_slice_upload_metadata(path)

        cover = str(metadata.get("cover") or "")
        if cover:
            cover_path = Path(cover)
            if cover_path.is_file():
                cover_path.unlink()

    def _sanitize_error(self, error: Any) -> str:
        text = str(error)
        for value in self.settings.sensitive_values:
            if value:
                text = text.replace(value, "[REDACTED]")
        return text[:2000]

    def _finish(self, result: UploadResult) -> UploadResult:
        write_upload_status(self.settings, result)
        return result


def write_upload_status(
    settings: UploadSettings,
    result: UploadResult,
) -> None:
    status_file = settings.status_file
    status_file.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    try:
        previous = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass

    last_bvid = result.bvid or str(previous.get("last_successful_bvid") or "")
    payload = {
        **asdict(result),
        "updated_at": time.time(),
        "queue_counts": get_upload_queue_counts(settings.db_path),
        "last_successful_bvid": last_bvid,
    }
    temp_path = status_file.with_name(
        f"{status_file.name}.{os.getpid()}.tmp"
    )
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_path, status_file)


def settings_from_environment() -> UploadSettings:
    project_root = Path(
        os.environ.get(
            "BILIVE_DIR",
            Path(__file__).resolve().parents[2],
        )
    ).resolve()
    config_path = Path(
        os.environ.get("BILIVE_CONFIG", project_root / "bilive-server.toml")
    )
    config = toml.load(config_path)
    upload_config = config.get("upload", {})
    video_config = config.get("video", {})
    runtime_dir = Path(
        os.environ.get("BILIVE_LOG_DIR", project_root / "logs")
    ) / "runtime"
    cookie_file = Path(
        os.environ.get(
            "BILIVE_COOKIE_FILE",
            project_root / ".secrets" / "bilibili.cookie",
        )
    )
    cookies = parse_cookie_file(cookie_file) if cookie_file.is_file() else {}
    return UploadSettings(
        db_path=Path(
            os.environ.get(
                "BILIVE_DB_PATH",
                project_root / "src" / "db" / "data.db",
            )
        ),
        cookie_file=cookie_file,
        status_file=Path(
            os.environ.get(
                "BILIVE_UPLOAD_STATUS_FILE",
                runtime_dir / "upload-status.json",
            )
        ),
        lock_file=Path(
            os.environ.get(
                "BILIVE_UPLOAD_LOCK_FILE",
                runtime_dir / "upload.lock",
            )
        ),
        poll_interval_seconds=float(
            upload_config.get("poll_interval_seconds", 10)
        ),
        max_attempts=int(upload_config.get("max_attempts", 3)),
        retry_base_seconds=float(upload_config.get("retry_base_seconds", 30)),
        auth_retry_seconds=float(upload_config.get("auth_retry_seconds", 120)),
        delete_after_success=bool(upload_config.get("delete_after_success", True)),
        upload_line=str(
            upload_config.get(
                "upload_line",
                video_config.get("upload_line", "auto"),
            )
        ),
        tid=int(video_config.get("tid", 138)),
        sensitive_values=tuple(value for value in cookies.values() if value),
    )


def build_runtime_client(settings: UploadSettings) -> BilibiliRuntimeClient:
    cookies = parse_cookie_file(settings.cookie_file)
    return BilibiliRuntimeClient(
        cookies=cookies,
        upload_line=settings.upload_line,
    )


def run_forever(
    settings: UploadSettings,
    client=None,
    *,
    client_factory=None,
    sleep=time.sleep,
    max_cycles: int | None = None,
) -> int:
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_stop)

    with UploadProcessLock(settings.lock_file):
        migrate_upload_queue(settings.db_path)
        recover_upload_queue(settings.db_path)
        runtime_client = client
        build_client = client_factory or (lambda: build_runtime_client(settings))
        cycles = 0
        while not stop_requested:
            if runtime_client is None:
                try:
                    runtime_client = build_client()
                except Exception as exc:
                    write_upload_status(
                        settings,
                        UploadResult(
                            status="paused_auth",
                            error=str(exc)[:2000],
                            next_attempt_at=time.time()
                            + settings.auth_retry_seconds,
                        ),
                    )
                    cycles += 1
                    if max_cycles is not None and cycles >= max_cycles:
                        break
                    sleep(settings.auth_retry_seconds)
                    continue

            worker = UploadWorker(settings, runtime_client)
            result = worker.process_one()
            cycles += 1
            if result.status == "paused_auth" and client is None:
                runtime_client = None
            if max_cycles is not None and cycles >= max_cycles:
                break
            delay = (
                settings.auth_retry_seconds
                if result.status == "paused_auth"
                else settings.poll_interval_seconds
            )
            sleep(delay)
    return 0


def _status_payload(settings: UploadSettings) -> dict[str, Any]:
    empty_counts = {status: 0 for status in UPLOAD_STATUSES}
    empty_counts["total"] = 0
    if not settings.db_path.is_file():
        return {
            "queue_counts": empty_counts,
            "items": [],
            "database": "missing",
            "status_file": str(settings.status_file),
            "lock_file": str(settings.lock_file),
        }
    try:
        counts = get_upload_queue_counts(settings.db_path)
        items = list_upload_queue(settings.db_path)
        database = "ready"
    except sqlite3.Error as exc:
        counts = empty_counts
        items = []
        database = f"unavailable: {exc}"
    return {
        "queue_counts": counts,
        "items": items,
        "database": database,
        "status_file": str(settings.status_file),
        "lock_file": str(settings.lock_file),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process the Bilibili upload queue.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="show queue status")
    mode.add_argument(
        "--check-auth",
        action="store_true",
        help="validate the configured Bilibili cookie",
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="process at most one due upload and exit",
    )
    args = parser.parse_args(argv)
    settings = settings_from_environment()

    if args.status:
        print(json.dumps(_status_payload(settings), ensure_ascii=False, indent=2))
        return 0

    try:
        if args.check_auth:
            client = build_runtime_client(settings)
            login = client.check_login()
            print(json.dumps(login or {"isLogin": False}, ensure_ascii=False))
            return 0 if login else 2

        if args.once:
            client = build_runtime_client(settings)
            with UploadProcessLock(settings.lock_file):
                migrate_upload_queue(settings.db_path)
                recover_upload_queue(settings.db_path)
                result = UploadWorker(settings, client).process_one()
            print(json.dumps(asdict(result), ensure_ascii=False))
            return 1 if result.status == "failed" else 0

        return run_forever(settings)
    except UploadAlreadyRunning as exc:
        print(str(exc))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
