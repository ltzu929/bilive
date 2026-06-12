"""Repair historical recordings and reset stale upload runtime state."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import subprocess
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from src.db.conn import migrate_upload_queue


MIN_RECOVERABLE_FLV_BYTES = 1024 * 1024


def reset_upload_database(
    db_path: str | Path,
    *,
    backup_dir: str | Path,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Create a consistent read-only backup and initialize an empty queue."""
    database = Path(db_path).expanduser().resolve()
    backups = Path(backup_dir).expanduser().resolve()
    backups.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    backup = backups / f"{database.stem}-{stamp}{database.suffix}"

    if database.exists():
        with closing(sqlite3.connect(database)) as source, closing(
            sqlite3.connect(backup)
        ) as target:
            source.backup(target)
        os.chmod(backup, stat.S_IREAD)

    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.execute("drop table if exists upload_queue")
        connection.commit()

    for suffix in ("-wal", "-shm"):
        candidate = Path(f"{database}{suffix}")
        try:
            candidate.unlink(missing_ok=True)
        except PermissionError:
            pass

    migrate_upload_queue(database)
    return {
        "database_path": str(database),
        "backup_path": str(backup) if backup.exists() else "",
    }


def probe_media(path: str | Path) -> dict[str, Any]:
    media = Path(path)
    if not media.is_file():
        return {"valid": False, "error": f"missing file: {media}"}

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,duration",
        "-of",
        "json",
        str(media),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        payload = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        return {"valid": False, "error": str(exc)}

    streams = payload.get("streams") if isinstance(payload, dict) else []
    stream_types = [
        str(stream.get("codec_type"))
        for stream in streams or []
        if isinstance(stream, dict) and stream.get("codec_type")
    ]
    durations = []
    format_data = payload.get("format") if isinstance(payload, dict) else {}
    for value in [
        (format_data or {}).get("duration"),
        *[
            stream.get("duration")
            for stream in streams or []
            if isinstance(stream, dict)
        ],
    ]:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            durations.append(duration)

    duration = max(durations, default=0.0)
    valid = duration > 0 and "video" in stream_types and "audio" in stream_types
    return {
        "valid": valid,
        "duration": duration,
        "streams": stream_types,
        "error": "" if valid else "missing positive duration or audio/video stream",
    }


def validate_media(path: str | Path) -> dict[str, Any]:
    """Require usable metadata and successful start/middle/end decoding."""
    media = Path(path)
    result = probe_media(media)
    if not result.get("valid"):
        return result

    duration = float(result["duration"])
    sample_points = sorted({0.0, max(0.0, duration / 2), max(0.0, duration - 3)})
    for point in sample_points:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-ss",
            f"{point:.3f}",
            "-i",
            str(media),
            "-t",
            "3",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            os.devnull,
        ]
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=180,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return {
                **result,
                "valid": False,
                "error": f"decode failed at {point:.3f}s: {exc}",
            }
    return result


def remux_flv(source: Path, output: Path) -> bool:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts+discardcorrupt",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            timeout=3600,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return output.is_file() and output.stat().st_size > 0


def recover_recording(
    source_path: str | Path,
    *,
    execute: bool,
    delete_invalid: bool = False,
    validator: Callable[[Path], dict[str, Any]] = validate_media,
    remuxer: Callable[[Path, Path], bool] = remux_flv,
) -> dict[str, Any]:
    """Keep only a verified MP4 for one historical FLV."""
    source = Path(source_path)
    target = source.with_suffix(".mp4")
    result: dict[str, Any] = {
        "source": str(source),
        "target": str(target),
        "source_bytes": source.stat().st_size if source.exists() else 0,
    }

    existing = validator(target)
    if existing.get("valid"):
        if execute:
            source.unlink(missing_ok=True)
        return {
            **result,
            "status": "kept_existing_mp4",
            "validation": existing,
        }

    if result["source_bytes"] < MIN_RECOVERABLE_FLV_BYTES:
        if execute and delete_invalid:
            source.unlink(missing_ok=True)
            if target.exists() and not existing.get("valid"):
                target.unlink()
        return {
            **result,
            "status": (
                "deleted_invalid"
                if execute and delete_invalid
                else "invalid_preserved"
                if execute
                else "would_delete_invalid"
            ),
            "validation": existing,
        }

    if not execute:
        return {
            **result,
            "status": "would_attempt_recovery",
            "validation": probe_media(source),
        }

    temporary = target.with_name(f"{target.stem}.partial.mp4")
    temporary.unlink(missing_ok=True)
    remuxed = remuxer(source, temporary)
    recovered = validator(temporary) if remuxed else {
        "valid": False,
        "error": "ffmpeg remux failed",
    }
    if recovered.get("valid"):
        os.replace(temporary, target)
        source.unlink(missing_ok=True)
        return {
            **result,
            "status": "recovered",
            "validation": recovered,
        }

    temporary.unlink(missing_ok=True)
    return {
        **result,
        "status": "recovery_failed_preserved",
        "validation": recovered,
    }


def recover_recordings(
    videos_root: str | Path,
    *,
    execute: bool,
    delete_invalid: bool = False,
) -> dict[str, Any]:
    root = Path(videos_root).expanduser().resolve()
    items = [
        recover_recording(
            path,
            execute=execute,
            delete_invalid=delete_invalid,
        )
        for path in sorted(root.rglob("*.flv"))
    ]
    counts: dict[str, int] = {}
    for item in items:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "videos_root": str(root),
        "execute": execute,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
        "items": items,
    }


def audit_mp4_recordings(
    videos_root: str | Path,
    *,
    delete_invalid: bool = False,
    validator: Callable[[Path], dict[str, Any]] = validate_media,
) -> dict[str, Any]:
    """Validate every MP4 and optionally remove only confirmed failures."""
    root = Path(videos_root).expanduser().resolve()
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.mp4")):
        validation = validator(path)
        if validation.get("valid"):
            status = "valid"
        elif delete_invalid:
            path.unlink(missing_ok=True)
            status = "deleted_invalid"
        else:
            status = "invalid_preserved"
        item = {
            "path": str(path),
            "bytes": path.stat().st_size if path.exists() else 0,
            "status": status,
            "validation": validation,
        }
        items.append(item)
        counts[status] = counts.get(status, 0) + 1
    return {
        "videos_root": str(root),
        "delete_invalid": delete_invalid,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos-root", type=Path, required=True)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--delete-invalid",
        action="store_true",
        help="Delete files below the recoverable size threshold after inspection.",
    )
    parser.add_argument(
        "--audit-mp4",
        action="store_true",
        help="Validate MP4 streams and start/middle/end decoding.",
    )
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "recordings": recover_recordings(
            args.videos_root,
            execute=args.execute,
            delete_invalid=args.delete_invalid,
        )
    }
    if args.audit_mp4:
        report["mp4_audit"] = audit_mp4_recordings(
            args.videos_root,
            delete_invalid=args.execute and args.delete_invalid,
        )
    if args.execute and args.db_path:
        backup_dir = args.backup_dir or args.report.parent / "database-backups"
        report["database"] = reset_upload_database(
            args.db_path,
            backup_dir=backup_dir,
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
