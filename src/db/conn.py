from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger("bilive.db")


DATA_BASE_FILE = os.environ.get(
    "BILIVE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"),
)

UPLOAD_STATUSES = (
    "queued",
    "uploading",
    "uploaded",
    "publishing",
    "published",
    "failed",
)


def _database_path(db_path: str | Path | None = None) -> str:
    return str(Path(db_path or DATA_BASE_FILE))


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(_database_path(db_path), timeout=30)
    db.row_factory = sqlite3.Row
    return db


def migrate_upload_queue(db_path: str | Path | None = None) -> None:
    path = Path(_database_path(db_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()

    with connect(path) as db:
        version = int(db.execute("pragma user_version").fetchone()[0])
        if version >= 1:
            return
        db.execute(
            """
            create table if not exists upload_queue (
                id integer primary key autoincrement,
                video_path text,
                locked integer default 0,
                status text default 'queued',
                remote_filename text default '',
                attempts integer default 0,
                next_attempt_at real default 0,
                last_error text default '',
                bvid text default '',
                updated_at real default 0
            )
            """
        )
        existing = {
            row["name"] for row in db.execute("pragma table_info(upload_queue)")
        }
        additions = {
            "status": "text",
            "remote_filename": "text default ''",
            "attempts": "integer default 0",
            "next_attempt_at": "real default 0",
            "last_error": "text default ''",
            "bvid": "text default ''",
            "updated_at": "real default 0",
        }
        for column, definition in additions.items():
            if column not in existing:
                db.execute(
                    f"alter table upload_queue add column {column} {definition}"
                )

        db.execute(
            "create unique index if not exists idx_video_path "
            "on upload_queue(video_path)"
        )
        db.execute(
            """
            update upload_queue
            set status = case
                    when coalesce(locked, 0) = 0 then 'queued'
                    else 'failed'
                end,
                updated_at = case
                    when coalesce(updated_at, 0) = 0 then ?
                    else updated_at
                end
            where status is null or status = ''
            """,
            (now,),
        )
        db.execute("pragma user_version = 1")
        db.execute(
            """
            update upload_queue
            set remote_filename = coalesce(remote_filename, ''),
                attempts = coalesce(attempts, 0),
                next_attempt_at = coalesce(next_attempt_at, 0),
                last_error = coalesce(last_error, ''),
                bvid = coalesce(bvid, ''),
                updated_at = case
                    when coalesce(updated_at, 0) = 0 then ?
                    else updated_at
                end
            """,
            (now,),
        )


def create_table(db_path: str | Path | None = None) -> bool:
    try:
        migrate_upload_queue(db_path)
        return True
    except sqlite3.Error:
        logger.exception("migrate_upload_queue failed for %s", db_path)
        return False


def _fetch_item(
    db: sqlite3.Connection,
    video_path: str,
) -> dict[str, Any] | None:
    row = db.execute(
        "select * from upload_queue where video_path = ?",
        (str(video_path),),
    ).fetchone()
    return dict(row) if row else None


def get_upload_item(
    video_path: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as db:
        return _fetch_item(db, video_path)


def list_upload_queue(
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    with connect(db_path) as db:
        rows = db.execute("select * from upload_queue order by id").fetchall()
    return [dict(row) for row in rows]


def get_all_upload_queue(
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return list_upload_queue(db_path)


def insert_upload_queue(
    video_path: str,
    db_path: str | Path | None = None,
) -> bool:
    now = time.time()
    try:
        with connect(db_path) as db:
            db.execute(
                """
                insert into upload_queue (
                    video_path,
                    locked,
                    status,
                    remote_filename,
                    attempts,
                    next_attempt_at,
                    last_error,
                    bvid,
                    updated_at
                ) values (?, 0, 'queued', '', 0, 0, '', '', ?)
                """,
                (str(video_path), now),
            )
        return True
    except sqlite3.IntegrityError:
        logger.warning("insert_upload_queue skipped duplicate video_path=%s", video_path)
        return False


def peek_next_upload(
    db_path: str | Path | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    due_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        row = db.execute(
            """
            select *
            from upload_queue
            where status in ('queued', 'uploaded')
              and coalesce(next_attempt_at, 0) <= ?
            order by id
            limit 1
            """,
            (due_at,),
        ).fetchone()
    return dict(row) if row else None


def claim_next_upload(
    db_path: str | Path | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    claimed_at = time.time() if now is None else float(now)
    db = connect(db_path)
    try:
        db.execute("begin immediate")
        row = db.execute(
            """
            select *
            from upload_queue
            where status in ('queued', 'uploaded')
              and coalesce(next_attempt_at, 0) <= ?
            order by id
            limit 1
            """,
            (claimed_at,),
        ).fetchone()
        if row is None:
            db.commit()
            return None

        next_status = "uploading" if row["status"] == "queued" else "publishing"
        db.execute(
            """
            update upload_queue
            set status = ?, locked = 0, updated_at = ?
            where id = ?
            """,
            (next_status, claimed_at, row["id"]),
        )
        claimed = db.execute(
            "select * from upload_queue where id = ?",
            (row["id"],),
        ).fetchone()
        db.commit()
        return dict(claimed)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_upload_complete(
    video_path: str,
    remote_filename: str,
    *,
    db_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        db.execute(
            """
            update upload_queue
            set status = 'uploaded',
                locked = 0,
                remote_filename = ?,
                next_attempt_at = 0,
                last_error = '',
                updated_at = ?
            where video_path = ?
            """,
            (remote_filename, updated_at, str(video_path)),
        )
        return _fetch_item(db, video_path)


def mark_upload_published(
    video_path: str,
    bvid: str,
    *,
    db_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        db.execute(
            """
            update upload_queue
            set status = 'published',
                locked = 0,
                bvid = ?,
                next_attempt_at = 0,
                last_error = '',
                updated_at = ?
            where video_path = ?
            """,
            (bvid, updated_at, str(video_path)),
        )
        return _fetch_item(db, video_path)


def mark_upload_failed(
    video_path: str,
    error: str,
    *,
    db_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        db.execute(
            """
            update upload_queue
            set status = 'failed',
                locked = 1,
                next_attempt_at = 0,
                last_error = ?,
                updated_at = ?
            where video_path = ?
            """,
            (str(error), updated_at, str(video_path)),
        )
        return _fetch_item(db, video_path)


def schedule_upload_retry(
    video_path: str,
    error: str,
    *,
    max_attempts: int,
    retry_base_seconds: float,
    db_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        item = _fetch_item(db, video_path)
        if item is None:
            return None

        attempts = int(item["attempts"] or 0) + 1
        if attempts >= max(1, int(max_attempts)):
            status = "failed"
            locked = 1
            next_attempt_at = 0
        else:
            status = "uploaded" if item["remote_filename"] else "queued"
            locked = 0
            next_attempt_at = updated_at + (
                float(retry_base_seconds) * (2 ** (attempts - 1))
            )

        db.execute(
            """
            update upload_queue
            set status = ?,
                locked = ?,
                attempts = ?,
                next_attempt_at = ?,
                last_error = ?,
                updated_at = ?
            where video_path = ?
            """,
            (
                status,
                locked,
                attempts,
                next_attempt_at,
                str(error),
                updated_at,
                str(video_path),
            ),
        )
        return _fetch_item(db, video_path)


def defer_upload_for_auth(
    video_path: str,
    error: str,
    *,
    retry_at: float,
    db_path: str | Path | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        db.execute(
            """
            update upload_queue
            set status = case
                    when remote_filename is not null and remote_filename != ''
                        then 'uploaded'
                    else 'queued'
                end,
                locked = 0,
                next_attempt_at = ?,
                last_error = ?,
                updated_at = ?
            where video_path = ?
            """,
            (
                float(retry_at),
                str(error),
                updated_at,
                str(video_path),
            ),
        )
        return _fetch_item(db, video_path)


def recover_upload_queue(
    db_path: str | Path | None = None,
    *,
    now: float | None = None,
) -> None:
    updated_at = time.time() if now is None else float(now)
    with connect(db_path) as db:
        db.execute(
            """
            update upload_queue
            set status = 'queued', locked = 0, updated_at = ?
            where status = 'uploading'
            """,
            (updated_at,),
        )
        db.execute(
            """
            update upload_queue
            set status = case
                    when remote_filename is not null and remote_filename != ''
                        then 'uploaded'
                    else 'queued'
                end,
                locked = 0,
                updated_at = ?
            where status = 'publishing'
            """,
            (updated_at,),
        )


def get_upload_queue_counts(
    db_path: str | Path | None = None,
) -> dict[str, int]:
    counts = {status: 0 for status in UPLOAD_STATUSES}
    with connect(db_path) as db:
        rows = db.execute(
            "select status, count(*) as count from upload_queue group by status"
        ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["count"])
    counts["total"] = sum(
        count for status, count in counts.items() if status in UPLOAD_STATUSES
    )
    return counts


def delete_upload_queue(
    video_path: str,
    db_path: str | Path | None = None,
) -> bool:
    try:
        with connect(db_path) as db:
            db.execute(
                "delete from upload_queue where video_path = ?",
                (str(video_path),),
            )
        return True
    except sqlite3.Error:
        logger.exception("delete_upload_queue failed for video_path=%s", video_path)
        return False


def update_upload_queue_lock(
    video_path: str,
    locked: int,
    db_path: str | Path | None = None,
) -> bool:
    try:
        status = "queued" if int(locked) == 0 else "failed"
        with connect(db_path) as db:
            db.execute(
                """
                update upload_queue
                set locked = ?, status = ?, updated_at = ?
                where video_path = ?
                """,
                (int(locked), status, time.time(), str(video_path)),
            )
        return True
    except sqlite3.Error:
        logger.exception("update_upload_queue_lock failed for video_path=%s", video_path)
        return False


def get_single_upload_queue(
    db_path: str | Path | None = None,
) -> dict[str, str] | None:
    with connect(db_path) as db:
        row = db.execute(
            """
            select video_path
            from upload_queue
            where status in ('queued', 'uploaded') and locked = 0
            order by id
            limit 1
            """
        ).fetchone()
    return {"video_path": row["video_path"]} if row else None


def get_single_lock_queue(
    db_path: str | Path | None = None,
) -> dict[str, str] | None:
    with connect(db_path) as db:
        row = db.execute(
            """
            select video_path
            from upload_queue
            where locked = 1
            order by id
            limit 1
            """
        ).fetchone()
    return {"video_path": row["video_path"]} if row else None


def get_all_reserve_for_fixing_queue(
    db_path: str | Path | None = None,
) -> list[dict[str, str]]:
    with connect(db_path) as db:
        rows = db.execute(
            "select video_path from upload_queue where locked = 2 order by id"
        ).fetchall()
    return [{"video_path": row["video_path"]} for row in rows]


def delete_all_queue(db_path: str | Path | None = None) -> None:
    with connect(db_path) as db:
        db.execute("delete from upload_queue")


if __name__ == "__main__":
    print(get_all_upload_queue())
