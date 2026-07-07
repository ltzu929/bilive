# Copyright (c) 2024 bilive.
"""Upload worker: claims one due queue row and drives it through upload → publish.

The worker is the stateful core of the upload consumer. ``process_one`` peeks
the next due row, validates metadata, checks login, claims the row, then walks
``uploading → uploaded → publishing → published`` with retry/pause handling.
``write_upload_status`` atomically mirrors the latest result + queue counts to
``upload-status.json`` for the dashboard.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.db.conn import (
    claim_next_upload,
    defer_upload_for_auth,
    get_upload_queue_counts,
    mark_upload_complete,
    mark_upload_failed,
    mark_upload_published,
    schedule_upload_retry,
    peek_next_upload,
)
from src.upload.models import UploadMetadataError, UploadResult, UploadSettings
from src.upload.slice_metadata import (
    delete_slice_upload_metadata,
    read_slice_upload_metadata,
    slice_upload_metadata_path,
)


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