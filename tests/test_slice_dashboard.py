import json
from pathlib import Path

import pytest


@pytest.mark.anyio
async def test_slice_dashboard_reports_unavailable_when_videos_dir_missing(
    tmp_path, dashboard_client
):
    missing = tmp_path / "does-not-exist"
    async with dashboard_client(videos_root=missing) as client:
        response = await client.get("/api/slice-dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["status_counts"]["failed"] == 0
    assert str(missing) in body["directory"]
    assert body["directory"].startswith("unavailable: missing")
    assert body["queue"]["pending_tasks"] == 0


@pytest.mark.anyio
async def test_slice_dashboard_buckets_tasks_by_status(
    videos_root, make_room, dashboard_client
):
    room = make_room("22384516")

    # A pending source recording.
    pending = room / "22384516_20260527-12-55-32.mp4"
    pending.write_bytes(b"video")
    pending.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    pending.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    # A failed source recording carrying a failure marker.
    failed = room / "22384516_20260528-10-00-00.mp4"
    failed.write_bytes(b"video")
    failed.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    failed.with_suffix(".mp4.failed").write_text(
        json.dumps({"error": "whisper crashed", "error_type": "RuntimeError"}),
        encoding="utf-8",
    )

    # A done source recording.
    done = room / "22384516_20260529-10-00-00.mp4"
    done.write_bytes(b"video")
    done.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    done.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-dashboard")

    assert response.status_code == 200
    body = response.json()
    counts = body["status_counts"]
    assert counts["pending"] == 1
    assert counts["failed"] == 1
    assert counts["done"] == 1
    assert body["total"] == 3
    assert body["directory"] == "ready"

    # pending/failed are surfaced as items; done is summarized only by count.
    statuses = {item["status"] for item in body["items"]}
    assert statuses == {"pending", "failed"}

    # queue overview mirrors load_pending_queue_state.
    assert body["queue"]["pending_tasks"] == 1
    assert any("22384516_20260527" in src for src in body["queue"]["pending_sources"])


@pytest.mark.anyio
async def test_slice_dashboard_surfaces_failed_items_first(
    videos_root, make_room, dashboard_client
):
    room = make_room("22384516")

    failed = room / "22384516_20260527-12-55-32.mp4"
    failed.write_bytes(b"video")
    failed.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    failed.with_suffix(".mp4.failed").write_text(
        json.dumps({"error": "mimo timeout", "error_type": "TimeoutError"}),
        encoding="utf-8",
    )

    pending = room / "22384516_20260528-12-55-32.mp4"
    pending.write_bytes(b"video")
    pending.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    pending.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    async with dashboard_client(videos_root) as client:
        body = (await client.get("/api/slice-dashboard")).json()

    # Failures are the most actionable state, so they sort ahead of pending.
    assert [item["status"] for item in body["items"]] == ["failed", "pending"]
    failed_item = body["items"][0]
    assert failed_item["failure"]["error"] == "mimo timeout"
    assert failed_item["source_name"] == "22384516_20260527-12-55-32.mp4"


@pytest.mark.anyio
async def test_slice_dashboard_folds_running_into_processing_bucket(
    videos_root, make_room, dashboard_client, monkeypatch
):
    room = make_room("22384516")
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    # No state marker -> build_task_inventory may classify as "ready" or
    # "processing" depending on xml presence; force the "running" status by
    # monkeypatching _determine_status via the task_state module.
    from src.dashboard import task_state

    monkeypatch.setattr(
        task_state,
        "_determine_status",
        lambda **kwargs: "running",
    )

    async with dashboard_client(videos_root) as client:
        body = (await client.get("/api/slice-dashboard")).json()

    # "running" must be folded into the "processing" bucket, not double-counted.
    assert body["status_counts"]["processing"] == 1
    assert "running" not in body["status_counts"]


@pytest.mark.anyio
async def test_slice_dashboard_caps_items_at_max(
    videos_root, make_room, dashboard_client
):
    room = make_room("22384516")
    # Create more failed sources than the cap so we verify truncation.
    for idx in range(25):
        source = room / f"22384516_202605{20 + idx:02d}-12-55-32.mp4"
        source.write_bytes(b"video")
        source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
        source.with_suffix(".mp4.failed").write_text(
            json.dumps({"error": f"err {idx}", "error_type": "RuntimeError"}),
            encoding="utf-8",
        )

    async with dashboard_client(videos_root) as client:
        body = (await client.get("/api/slice-dashboard")).json()

    assert body["status_counts"]["failed"] == 25
    assert len(body["items"]) <= 20
    assert all(item["status"] == "failed" for item in body["items"])


@pytest.mark.anyio
async def test_slice_dashboard_endpoint_resolves_through_app_module(
    videos_root, dashboard_client, monkeypatch
):
    """The route must call src.dashboard.app.read_slice_dashboard so a dotted-path
    monkeypatch of that name takes effect (parity with /api/upload-dashboard)."""
    from src.dashboard import app as dashboard_app

    captured = {}

    def fake_read_slice_dashboard(root):
        captured["called"] = True
        captured["root"] = str(root)
        return {"status_counts": {}, "total": 0, "items": [], "fake": True}

    monkeypatch.setattr(dashboard_app, "read_slice_dashboard", fake_read_slice_dashboard)

    async with dashboard_client(videos_root) as client:
        body = (await client.get("/api/slice-dashboard")).json()

    assert captured["called"] is True
    assert body["fake"] is True


def test_read_slice_dashboard_helper_buckets_directly(videos_root, make_room):
    """The pure helper can be exercised without spinning up the app."""
    from src.dashboard._helpers import read_slice_dashboard

    room = make_room("22384516")
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    body = read_slice_dashboard(videos_root)
    assert body["status_counts"]["pending"] == 1
    assert body["total"] == 1
    assert body["items"][0]["status"] == "pending"
    assert body["directory"] == "ready"