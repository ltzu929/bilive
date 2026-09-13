import json

import pytest

from src.dashboard.file_store import DashboardFileStore
from src.dashboard.slice_control import start_slice_scan
from src.dashboard.task_state import build_task_inventory


@pytest.mark.anyio
async def test_named_mp4_rooms_list_detail_and_media(videos_root, make_room, dashboard_client):
    room = make_room("8792912 - 咩栗")
    make_room("8792912")
    source = room / "blive_8792912_2026-09-08-105557.mp4"
    source.write_bytes(b"recording")
    source.with_suffix(".xml").write_text("<i></i>")
    (room / "blive_8792912_2026-09-08-105557_injecting.flv").write_bytes(b"temp")
    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/rooms")
        assert response.json() == [{"room_id": "8792912", "name": "咩栗"}]
        response = await client.get("/api/source-recordings", params={"room_id": "8792912"})
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["room_name"] == "咩栗"
        assert row["recorded_at"] == "2026-09-08 10:55:57"
        assert row["source_rel_path"] == f"{room.name}/{source.name}"
        response = await client.get(f"/api/source-recordings/{row['task_id']}")
        assert response.status_code == 200
        assert response.json()["room_id"] == "8792912"
        response = await client.get(f"/api/media/{row['source_media_id']}")
        assert response.status_code == 200
        assert response.content == b"recording"
    result = start_slice_scan(videos_root, task_id=row["task_id"])
    assert result["queued"] == 1
    marker = json.loads(source.with_suffix(".mp4.pending").read_text(encoding="utf-8"))
    assert marker["room_id"] == "8792912"
    assert marker["video_rel_path"] == row["source_rel_path"]


def test_named_mp4_deduplicates_flv_and_lists_slices(videos_root, make_room):
    room = make_room("8792912 - 咩栗")
    stem = "8792912_20260908-10-55-57"
    for extension in ("mp4", "flv"):
        (room / f"{stem}.{extension}").write_bytes(b"source")
    (room / f"{stem}.xml").write_text("<i></i>")
    (room / f"10s_{stem}.mp4").write_bytes(b"slice")
    tasks = build_task_inventory(videos_root, room_id="8792912")
    assert len(tasks) == 1
    assert tasks[0]["source_name"] == f"{stem}.mp4"
    store = DashboardFileStore(videos_root)
    assert [item.room_id for item in store.list_slices("8792912")] == ["8792912"]
    assert len(store.list_slices()) == 1
    assert start_slice_scan(videos_root)["queued"] == 1


def test_room_dropdown_uses_same_profile_name(videos_root, make_room):
    make_room("8792912 - 咩栗")
    profiles = videos_root / ".bilive-state" / "streamers"
    profiles.mkdir(parents=True)
    (profiles / "8792912.json").write_text(json.dumps({"profile": {"display_name": "咩栗新名字"}}), encoding="utf-8")
    assert DashboardFileStore(videos_root).list_rooms()[0].name == "咩栗新名字"


def test_unconverted_flv_is_not_a_workbench_source(videos_root, make_room):
    room = make_room("8792912 - 咩栗")
    source = room / "blive_8792912_2026-09-08-105557.flv"
    source.write_bytes(b"unconverted")
    source.with_suffix(".xml").write_text("<i/>")
    assert build_task_inventory(videos_root) == []
    assert start_slice_scan(videos_root)["queued"] == 0


def test_upload_dashboard_reads_sidecar_from_named_room_directory(
    videos_root,
    monkeypatch,
    make_room,
):
    from src.dashboard._helpers import read_upload_dashboard
    from src.db import conn
    from src.upload.slice_metadata import write_slice_upload_metadata

    room = make_room("22384516 - 呜米")
    video = room / "final.mp4"
    video.write_bytes(b"fixture")
    write_slice_upload_metadata(
        video,
        title="fixture",
        source_task_id="source",
        segment_id="segment",
    )
    monkeypatch.setenv("BILIVE_VIDEOS_DIR", str(videos_root))
    # Path shape matches production Windows queue rows, with a named room dir.
    conn.insert_upload_queue(r"D:\alldata\pi\bilive\Videos\22384516 - 呜米\final.mp4")
    item = read_upload_dashboard()["items"][0]
    assert item["room"] == "22384516 - 呜米"
    assert item["source_task_id"] == "source"
    assert item["segment_id"] == "segment"


def test_progress_rel_path_prefers_named_room_directory(videos_root, make_room):
    from src.dashboard._helpers import enrich_slice_progress

    named = make_room("8792912 - 咩栗")
    make_room("8792912")
    source = named / "blive_8792912_2026-09-08-105557.mp4"
    source.write_bytes(b"recording")
    store = DashboardFileStore(videos_root)
    # Windows absolute source_path is unresolvable on this node; fall back to room scan.
    enriched = enrich_slice_progress(
        {
            "room_id": "8792912",
            "source_name": source.name,
            "source_path": r"D:\alldata\pi\bilive\Videos\8792912 - 咩栗\blive_8792912_2026-09-08-105557.mp4",
        },
        store,
    )
    assert enriched["source_rel_path"] == f"{named.name}/{source.name}"


def test_progress_rel_path_prefers_named_dir_when_file_missing(videos_root, make_room):
    from src.dashboard._helpers import enrich_slice_progress

    make_room("8792912 - 咩栗")
    make_room("8792912")
    store = DashboardFileStore(videos_root)
    enriched = enrich_slice_progress(
        {
            "room_id": "8792912",
            "source_name": "blive_8792912_2026-09-08-105557.mp4",
            "source_path": "",
        },
        store,
    )
    assert enriched["source_rel_path"] == "8792912 - 咩栗/blive_8792912_2026-09-08-105557.mp4"
