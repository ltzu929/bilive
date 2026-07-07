# Copyright (c) 2024 bilive.
"""Bilibili upload queue consumer — CLI entry point + run loop.

The worker/client/lock/settings/cookie building blocks live in sibling modules
and are re-exported here for back-compat: ``tests/test_upload_worker.py``
imports these names from ``src.upload.upload`` and monkeypatches
``build_runtime_client`` / ``settings_from_environment`` / ``run_forever`` by
dotted path. Because ``main`` and ``run_forever`` live in *this* module and
call those names through this module's globals, those monkeypatches take effect.
"""

from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import time
from dataclasses import asdict
from typing import Any

from src.db.conn import (
    UPLOAD_STATUSES,
    get_upload_queue_counts,
    list_upload_queue,
    migrate_upload_queue,
    recover_upload_queue,
)
from src.upload.bilibili_runtime import BilibiliRuntimeClient, build_runtime_client
from src.upload.cookie import parse_cookie_file
from src.upload.lock import UploadAlreadyRunning, UploadProcessLock
from src.upload.models import (
    UploadMetadataError,
    UploadResult,
    UploadSettings,
    settings_from_environment,
)
from src.upload.worker import UploadWorker, write_upload_status


__all__ = [
    # entry points / monkeypatch targets (must stay at module scope here)
    "main",
    "run_forever",
    "settings_from_environment",
    "build_runtime_client",
    # re-exported building blocks (imported by tests/test_upload_worker.py)
    "BilibiliRuntimeClient",
    "UploadAlreadyRunning",
    "UploadProcessLock",
    "UploadSettings",
    "UploadResult",
    "UploadMetadataError",
    "UploadWorker",
    "parse_cookie_file",
    "write_upload_status",
]


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