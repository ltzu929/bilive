# Copyright (c) 2024 bilive.
"""Phase 3 (self-evolution) tests: slice_performance table, feature sidecar,
published-stats poller, advisory recommender, and the read-only panel route."""

import pytest

from src.db import conn


# --------------------------------------------------------------------------- #
# conn.py slice_performance table
# --------------------------------------------------------------------------- #
def test_migrate_slice_performance_idempotent(tmp_path):
    db_path = tmp_path / "perf.db"
    conn.migrate_slice_performance(db_path)
    # Running twice must not raise (create table if not exists).
    conn.migrate_slice_performance(db_path)
    assert conn.slice_performance_available(db_path) is True


def test_slice_performance_available_false_when_absent(tmp_path):
    db_path = tmp_path / "missing.db"
    # No migration → table absent → available() must be False (no build).
    assert conn.slice_performance_available(db_path) is False


def test_get_slice_performance_returns_empty_when_table_absent(tmp_path):
    db_path = tmp_path / "missing.db"
    assert conn.get_slice_performance(db_path) == []


def test_upsert_partial_columns_do_not_clobber(tmp_path):
    db_path = tmp_path / "perf.db"
    conn.migrate_slice_performance(db_path)

    # Publish-time path writes feature columns only.
    conn.upsert_slice_performance(
        "BV1",
        {"title": "clip", "lag_seconds": 2.5, "quality_score": 0.8},
        db_path=db_path,
    )
    # Later stat-poll path writes stat columns only.
    conn.upsert_slice_performance(
        "BV1",
        {"view": 1000, "likes": 50, "collected_at": 123.0},
        db_path=db_path,
    )

    rows = conn.get_slice_performance(db_path)
    assert len(rows) == 1
    row = rows[0]
    # Feature columns survive the stat update.
    assert row["title"] == "clip"
    assert row["lag_seconds"] == 2.5
    assert row["quality_score"] == 0.8
    # Stat columns were added.
    assert row["view"] == 1000
    assert row["likes"] == 50


def test_upsert_ignores_unknown_columns_and_blank_bvid(tmp_path):
    db_path = tmp_path / "perf.db"
    conn.migrate_slice_performance(db_path)

    assert conn.upsert_slice_performance("", {"view": 1}, db_path=db_path) is False
    assert conn.upsert_slice_performance(
        "BV2", {"view": 5, "not_a_column": 9}, db_path=db_path
    ) is True
    rows = conn.get_slice_performance(db_path)
    assert rows[0]["bvid"] == "BV2"
    assert rows[0]["view"] == 5


def test_get_slice_performance_sorted_by_view_desc(tmp_path):
    db_path = tmp_path / "perf.db"
    conn.migrate_slice_performance(db_path)
    conn.upsert_slice_performance("BVlow", {"view": 10}, db_path=db_path)
    conn.upsert_slice_performance("BVhigh", {"view": 9999}, db_path=db_path)
    conn.upsert_slice_performance("BVmid", {"view": 500}, db_path=db_path)

    rows = conn.get_slice_performance(db_path)
    assert [r["bvid"] for r in rows] == ["BVhigh", "BVmid", "BVlow"]


def test_mark_upload_published_snapshots_features(tmp_path):
    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)
    video_path = str(tmp_path / "clip.mp4")
    conn.insert_upload_queue(video_path, db_path=db_path)

    features = {
        "title": "highlight",
        "quality_score": 0.9,
        "lag_seconds": 3.0,
        "burst_ratio": 2.5,
        "danmaku_count": 42,
    }
    conn.mark_upload_published(
        video_path, "BVabc", features=features, db_path=db_path, now=100.0
    )

    rows = conn.get_slice_performance(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["bvid"] == "BVabc"
    assert row["title"] == "highlight"
    assert row["quality_score"] == 0.9
    assert row["danmaku_count"] == 42
    assert row["video_path"] == video_path
    assert row["collected_at"] == 100.0


def test_mark_upload_published_without_features_does_not_create_table(tmp_path):
    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)
    video_path = str(tmp_path / "clip.mp4")
    conn.insert_upload_queue(video_path, db_path=db_path)

    conn.mark_upload_published(video_path, "BVnofeat", db_path=db_path)
    # No features → no slice_performance snapshot/table.
    assert conn.slice_performance_available(db_path) is False


# --------------------------------------------------------------------------- #
# slice_metadata feature sidecar
# --------------------------------------------------------------------------- #
def test_feature_sidecar_roundtrip(tmp_path):
    from src.upload import slice_metadata

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")

    slice_metadata.write_slice_features(
        video,
        {
            "title": "t",
            "quality_score": 0.7,
            "danmaku_count": None,  # None is dropped
            "unknown": "ignored",  # not in SLICE_FEATURE_FIELDS
        },
    )
    assert slice_metadata.slice_features_path(video).is_file()

    data = slice_metadata.read_slice_features(video)
    assert data == {"title": "t", "quality_score": 0.7}

    slice_metadata.delete_slice_features(video)
    assert slice_metadata.read_slice_features(video) is None


def test_read_slice_features_missing_returns_none(tmp_path):
    from src.upload import slice_metadata

    assert slice_metadata.read_slice_features(tmp_path / "nope.mp4") is None


# --------------------------------------------------------------------------- #
# published_stats poller (injected fetcher, never hits network)
# --------------------------------------------------------------------------- #
def _seed_published(db_path, bvids):
    conn.migrate_upload_queue(db_path)
    for i, bvid in enumerate(bvids):
        video_path = f"clip-{i}.mp4"
        conn.insert_upload_queue(video_path, db_path=db_path)
        conn.mark_upload_published(video_path, bvid, db_path=db_path)


def test_refresh_published_stats_updates_and_isolates_failures(tmp_path):
    from src.analytics import published_stats

    db_path = tmp_path / "upload.db"
    _seed_published(db_path, ["BVok", "BVboom"])

    def fetcher(bvid):
        if bvid == "BVboom":
            raise RuntimeError("network down")
        return {"view": 100, "likes": 5}

    slept = []
    summary = published_stats.refresh_published_stats(
        db_path=db_path,
        fetcher=fetcher,
        rate_limit_seconds=0.5,
        now=lambda: 42.0,
        sleep=slept.append,
    )

    assert summary["total"] == 2
    assert summary["updated"] == 1
    assert summary["failed"] == 1
    # One inter-request sleep between the two published rows.
    assert slept == [0.5]

    rows = {r["bvid"]: r for r in conn.get_slice_performance(db_path)}
    assert rows["BVok"]["view"] == 100
    assert rows["BVok"]["collected_at"] == 42.0


def test_refresh_published_stats_no_published_rows(tmp_path):
    from src.analytics import published_stats

    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)

    summary = published_stats.refresh_published_stats(
        db_path=db_path, fetcher=lambda bvid: {"view": 1}
    )
    assert summary == {"total": 0, "updated": 0, "failed": 0}


# --------------------------------------------------------------------------- #
# recommender (pure functions)
# --------------------------------------------------------------------------- #
def test_build_recommendations_insufficient_data():
    from src.analytics import recommender

    rows = [{"bvid": "BV1", "view": 10, "lag_seconds": 1.0}]
    report = recommender.build_recommendations(rows, min_samples=5)
    assert report["insufficient_data"] is True
    assert report["sample_size"] == 1
    assert report["config_suggestions"] == {}


def test_build_recommendations_top_cohort_and_few_shot():
    from src.analytics import recommender

    rows = []
    # Six rows; top performers have higher lag_seconds.
    for i in range(6):
        rows.append(
            {
                "bvid": f"BV{i}",
                "view": (i + 1) * 1000,
                "lag_seconds": 1.0 + i,  # correlates with view
                "likes": (i + 1) * 10,
                "title": f"title-{i}",
            }
        )

    report = recommender.build_recommendations(
        rows,
        current_config={"slice.burst.burst_lag_seconds": 1.0},
        min_samples=5,
        top_ratio=0.5,
    )
    assert report["insufficient_data"] is False
    assert report["sample_size"] == 6
    lag = report["metrics"]["lag_seconds"]
    assert lag["config_key"] == "slice.burst.burst_lag_seconds"
    assert lag["current"] == 1.0
    # Top cohort has higher lag than overall → positive delta.
    assert lag["top_mean"] > lag["overall_mean"]
    assert "slice.burst.burst_lag_seconds" in report["config_suggestions"]
    assert report["few_shot"]  # top performers surfaced
    assert report["few_shot"][0]["view"] == 6000


def test_write_recommendations_persists_json(tmp_path):
    from src.analytics import recommender

    report = {"sample_size": 1, "few_shot": [{"title": "x"}]}
    paths = recommender.write_recommendations(report, tmp_path / "out")
    assert paths["report"].is_file()
    assert paths["few_shot"].is_file()


# --------------------------------------------------------------------------- #
# read-only dashboard route
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_slice_performance_route_unavailable(
    videos_root, dashboard_client, monkeypatch, tmp_path
):
    missing_db = tmp_path / "missing.db"
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(missing_db))

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["items"] == []


@pytest.mark.anyio
async def test_slice_performance_route_ok(
    videos_root, dashboard_client, monkeypatch, tmp_path
):
    db_path = tmp_path / "perf.db"
    conn.migrate_slice_performance(db_path)
    conn.upsert_slice_performance(
        "BVpanel", {"title": "clip", "view": 1234, "likes": 56}, db_path=db_path
    )
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(db_path))

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["bvid"] == "BVpanel"
    assert payload["items"][0]["view"] == 1234
