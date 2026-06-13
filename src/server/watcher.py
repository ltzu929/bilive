"""Process dashboard-created slice task markers on the Windows PC."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Callable

from src.autoslice.mllm_sdk.managed_runtime import managed_llm_batch
from src.burn.task_history import write_task_history
from src.config.server_config import VIDEOS_DIR
from src.log.logger import scan_log
from src.server.action_jobs import process_action_jobs
from src.server.worker_lock import (
    WorkerAlreadyRunning,
    WorkerProcessLock,
    default_worker_lock_path,
    pid_is_running,
)


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def recover_processing_markers(
    videos_dir: str | Path,
    *,
    pid_checker: Callable[[int], bool] = pid_is_running,
) -> int:
    """Return abandoned processing markers to the pending queue."""
    root = Path(videos_dir)
    recovered = 0
    if not root.is_dir():
        return recovered

    for processing in sorted(root.rglob("*.mp4.processing")):
        try:
            marker = json.loads(processing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker = {}
        try:
            owner = int(marker.get("worker_pid") or 0)
        except (TypeError, ValueError):
            owner = 0
        if owner > 0 and pid_checker(owner):
            continue

        pending = processing.with_suffix(".pending")
        marker.pop("worker_pid", None)
        marker["recovered_from"] = "processing"
        marker["recovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not pending.exists():
            _write_json_atomic(pending, marker)
            write_task_history(
                processing.with_suffix(""),
                status="pending",
                videos_root=root,
                started_at=marker["recovered_at"],
            )
        processing.unlink(missing_ok=True)
        recovered += 1
    return recovered


def _claim_pending(pending: Path) -> tuple[Path, dict] | None:
    """Atomically rename pending to processing so only one process can own it."""
    processing = pending.with_suffix(".processing")
    try:
        with WorkerProcessLock(pending.parent / ".bilive-marker-claim.lock"):
            if not pending.is_file():
                return None
            os.replace(pending, processing)
            marker = json.loads(processing.read_text(encoding="utf-8"))
            marker["worker_pid"] = os.getpid()
            marker["claimed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _write_json_atomic(processing, marker)
    except (FileNotFoundError, WorkerAlreadyRunning):
        return None
    return processing, marker


def _video_path(marker: dict, videos_dir: Path, processing: Path) -> Path:
    relative = str(marker.get("video_rel_path") or "")
    if relative:
        candidate = (videos_dir / relative).resolve()
        candidate.relative_to(videos_dir.resolve())
        return candidate
    absolute = str(marker.get("video_path") or "")
    if absolute:
        return Path(absolute).expanduser().resolve()
    return processing.with_suffix("")


def _relative_output_slices(output_slices, videos_dir: Path):
    if not isinstance(output_slices, list):
        return None

    normalized = []
    root = videos_dir.resolve()
    for item in output_slices:
        path_text = str(item)
        try:
            normalized.append(Path(path_text).resolve().relative_to(root).as_posix())
        except (OSError, ValueError):
            normalized.append(path_text.replace("\\", "/"))
    return normalized


def process_pending_videos(videos_dir: str | Path | None = None) -> int:
    """Process every marker that can be atomically claimed."""
    root = Path(videos_dir or VIDEOS_DIR).expanduser().resolve()
    if not root.is_dir():
        scan_log.warning(f"Videos dir not found: {root}")
        return 0

    with managed_llm_batch():
        return _process_pending_root(root)


def _process_pending_root(root: Path) -> int:
    recover_processing_markers(root)
    processed = process_action_jobs(root)
    for pending in sorted(root.rglob("*.mp4.pending")):
        processing: Path | None = None
        marker: dict = {}
        video = pending.with_suffix("")
        try:
            claimed = _claim_pending(pending)
            if claimed is None:
                continue
            processing, marker = claimed
            video = _video_path(marker, root, processing)
            if not video.is_file():
                raise FileNotFoundError(f"Video file not found: {video}")

            started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            write_task_history(
                video,
                status="processing",
                videos_root=root,
                started_at=started_at,
                worker_pid=os.getpid(),
            )
            action = str(marker.get("action") or "slice")
            scan_log.info(f"Processing {action}: {video}")
            worker_pid = os.getpid()
            slice_options = marker.get("slice_options", {}) or {}

            if action != "slice":
                raise ValueError(f"Unknown action: {action}")

            from src.burn.slice_only import slice_only

            pipeline_result = slice_only(str(video), **slice_options)
            if not isinstance(pipeline_result, dict):
                pipeline_result = {}
            if pipeline_result.get("status") == "failed":
                raise RuntimeError(
                    pipeline_result.get("error") or "slice pipeline failed"
                )

            marker.pop("worker_pid", None)
            marker["processed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            done = processing.with_suffix(".done")
            _write_json_atomic(done, marker)
            processing.unlink()
            video.with_suffix(".mp4.failed").unlink(missing_ok=True)

            write_task_history(
                video,
                status=(
                    "skipped"
                    if pipeline_result.get("status") == "skipped"
                    else "done"
                ),
                videos_root=root,
                started_at=started_at,
                worker_pid=worker_pid,
                slice_count=int(pipeline_result.get("slice_count") or 0),
                output_slices=_relative_output_slices(
                    pipeline_result.get("output_slices"),
                    root,
                ),
                segments=pipeline_result.get("segments"),
                diagnostics=pipeline_result.get("diagnostics"),
            )
            processed += 1
            scan_log.info(f"Successfully processed: {video}")
        except Exception as exc:
            active_marker = processing or pending
            scan_log.error(f"Processing failed for {active_marker}: {exc}")
            if video.is_file():
                try:
                    write_task_history(
                        video,
                        status="failed",
                        videos_root=root,
                        worker_pid=os.getpid(),
                        error=str(exc),
                        failure={
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "stage": "worker",
                        },
                    )
                except Exception:
                    pass

            failure = {
                **marker,
                "status": "failed",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "failed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            failure.pop("worker_pid", None)
            try:
                _write_json_atomic(video.with_suffix(".mp4.failed"), failure)
            finally:
                active_marker.unlink(missing_ok=True)

    return processed


def run_watcher(interval: int = 30, videos_dir: str | Path | None = None) -> None:
    scan_log.info("Watcher started. Monitoring for .pending files...")
    while True:
        try:
            count = process_pending_videos(videos_dir)
            if count > 0:
                scan_log.info(f"Processed {count} video(s)")
        except Exception as exc:
            scan_log.error(f"Watcher error: {exc}")
        time.sleep(interval)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process pending tasks once")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--videos-dir", default=None)
    parser.add_argument("--lock-file", default=None)
    args = parser.parse_args(argv)

    lock_path = Path(args.lock_file) if args.lock_file else default_worker_lock_path()
    try:
        with WorkerProcessLock(lock_path):
            if args.once:
                count = process_pending_videos(args.videos_dir)
                scan_log.info(f"One-shot worker complete. Processed {count} video(s).")
                return 0
            run_watcher(interval=args.interval, videos_dir=args.videos_dir)
    except WorkerAlreadyRunning as exc:
        scan_log.info(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
