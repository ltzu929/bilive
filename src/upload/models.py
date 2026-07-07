# Copyright (c) 2024 bilive.
"""Dataclass models + settings loader for the upload consumer.

``UploadSettings`` is the frozen configuration bundle built from
``bilive-server.toml`` + environment variables by ``settings_from_environment``.
``UploadResult`` is the per-cycle outcome written to ``upload-status.json``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import toml

from src.upload.cookie import parse_cookie_file


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