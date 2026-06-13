import sqlite3

from src.db.conn import (
    claim_next_upload,
    get_upload_item,
    get_upload_queue_counts,
    insert_upload_queue,
    list_upload_queue,
    mark_upload_complete,
    mark_upload_failed,
    mark_upload_published,
    migrate_upload_queue,
    recover_upload_queue,
    schedule_upload_retry,
)


def create_legacy_queue(db_path, rows):
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            create table upload_queue (
                id integer primary key autoincrement,
                video_path text,
                locked integer default 0
            )
            """
        )
        db.execute("create unique index idx_video_path on upload_queue(video_path)")
        db.executemany(
            "insert into upload_queue (video_path, locked) values (?, ?)",
            rows,
        )


def test_migrate_upload_queue_preserves_locked_rows_as_failed(tmp_path):
    db_path = tmp_path / "data.db"
    create_legacy_queue(
        db_path,
        [
            ("queued.mp4", 0),
            ("locked.mp4", 1),
            ("reserved.mp4", 2),
        ],
    )

    migrate_upload_queue(db_path)
    migrate_upload_queue(db_path)

    with sqlite3.connect(db_path) as db:
        assert db.execute("pragma user_version").fetchone()[0] == 1
    rows = list_upload_queue(db_path)
    assert [(row["video_path"], row["status"], row["locked"]) for row in rows] == [
        ("queued.mp4", "queued", 0),
        ("locked.mp4", "failed", 1),
        ("reserved.mp4", "failed", 2),
    ]
    assert all(row["attempts"] == 0 for row in rows)
    assert claim_next_upload(db_path, now=100)["video_path"] == "queued.mp4"
    assert claim_next_upload(db_path, now=100) is None


def test_claim_transitions_upload_and_publish_phases(tmp_path):
    db_path = tmp_path / "data.db"
    migrate_upload_queue(db_path)
    assert insert_upload_queue("clip.mp4", db_path=db_path) is True

    upload_claim = claim_next_upload(db_path, now=100)
    assert upload_claim["status"] == "uploading"

    mark_upload_complete(
        "clip.mp4",
        "remote-filename",
        db_path=db_path,
        now=101,
    )
    assert get_upload_item("clip.mp4", db_path)["status"] == "uploaded"

    publish_claim = claim_next_upload(db_path, now=102)
    assert publish_claim["status"] == "publishing"
    assert publish_claim["remote_filename"] == "remote-filename"

    mark_upload_published(
        "clip.mp4",
        "BV1test",
        db_path=db_path,
        now=103,
    )
    published = get_upload_item("clip.mp4", db_path)
    assert published["status"] == "published"
    assert published["bvid"] == "BV1test"
    assert claim_next_upload(db_path, now=104) is None


def test_publish_retry_preserves_remote_filename_and_stops_at_limit(tmp_path):
    db_path = tmp_path / "data.db"
    migrate_upload_queue(db_path)
    insert_upload_queue("clip.mp4", db_path=db_path)
    claim_next_upload(db_path, now=100)
    mark_upload_complete(
        "clip.mp4",
        "remote-filename",
        db_path=db_path,
        now=101,
    )
    claim_next_upload(db_path, now=102)

    first = schedule_upload_retry(
        "clip.mp4",
        "temporary publish failure",
        max_attempts=2,
        retry_base_seconds=30,
        db_path=db_path,
        now=103,
    )
    assert first["status"] == "uploaded"
    assert first["remote_filename"] == "remote-filename"
    assert first["attempts"] == 1
    assert first["next_attempt_at"] == 133
    assert claim_next_upload(db_path, now=132) is None
    assert claim_next_upload(db_path, now=133)["status"] == "publishing"

    second = schedule_upload_retry(
        "clip.mp4",
        "permanent publish failure",
        max_attempts=2,
        retry_base_seconds=30,
        db_path=db_path,
        now=134,
    )
    assert second["status"] == "failed"
    assert second["locked"] == 1
    assert second["attempts"] == 2
    assert second["remote_filename"] == "remote-filename"
    assert claim_next_upload(db_path, now=1000) is None


def test_recover_upload_queue_restores_correct_phase(tmp_path):
    db_path = tmp_path / "data.db"
    migrate_upload_queue(db_path)
    insert_upload_queue("uploading.mp4", db_path=db_path)
    insert_upload_queue("publishing.mp4", db_path=db_path)

    claim_next_upload(db_path, now=100)
    claim_next_upload(db_path, now=100)
    mark_upload_complete(
        "publishing.mp4",
        "remote-publishing",
        db_path=db_path,
        now=101,
    )
    claim_next_upload(db_path, now=102)

    recover_upload_queue(db_path, now=200)

    assert get_upload_item("uploading.mp4", db_path)["status"] == "queued"
    recovered_publish = get_upload_item("publishing.mp4", db_path)
    assert recovered_publish["status"] == "uploaded"
    assert recovered_publish["remote_filename"] == "remote-publishing"


def test_queue_counts_include_each_state(tmp_path):
    db_path = tmp_path / "data.db"
    migrate_upload_queue(db_path)
    insert_upload_queue("queued.mp4", db_path=db_path)
    insert_upload_queue("failed.mp4", db_path=db_path)
    mark_upload_failed("failed.mp4", "bad metadata", db_path=db_path, now=100)

    counts = get_upload_queue_counts(db_path)

    assert counts["total"] == 2
    assert counts["queued"] == 1
    assert counts["failed"] == 1


def test_read_only_queue_queries_do_not_run_migration(tmp_path, monkeypatch):
    from src.db import conn

    db_path = tmp_path / "data.db"
    migrate_upload_queue(db_path)
    insert_upload_queue("queued.mp4", db_path=db_path)

    monkeypatch.setattr(
        conn,
        "migrate_upload_queue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("read query attempted migration")
        ),
    )

    assert conn.get_upload_item("queued.mp4", db_path)["status"] == "queued"
    assert conn.list_upload_queue(db_path)[0]["video_path"] == "queued.mp4"
    assert conn.peek_next_upload(db_path, now=100)["video_path"] == "queued.mp4"
    assert conn.get_upload_queue_counts(db_path)["queued"] == 1
