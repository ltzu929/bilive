import json

from src.burn.task_history import read_task_history
from src.dashboard import slice_control


def test_start_slice_scan_writes_pending_markers_for_pc_worker(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260524-12-57-08.mp4"
    source.write_bytes(b"mp4")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    (room / "120s_22384516_20260524-12-57-08.mp4").write_bytes(b"slice")

    result = slice_control.start_slice_scan(videos_root=videos)

    pending_path = source.with_suffix(".mp4.pending")
    marker = json.loads(pending_path.read_text(encoding="utf-8"))
    assert result["status"] == "queued"
    assert result["queued"] == 1
    assert result["skipped"] == 1
    assert marker["video_rel_path"] == "22384516/22384516_20260524-12-57-08.mp4"
    assert marker["room_id"] == "22384516"
    assert marker["action"] == "slice"
    assert not (room / "120s_22384516_20260524-12-57-08.mp4.pending").exists()
    assert read_task_history(source)["status"] == "pending"


def test_start_slice_scan_reports_empty_queue_when_nothing_is_ready(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260524-12-57-08.mp4").write_bytes(b"mp4")

    result = slice_control.start_slice_scan(videos_root=videos)

    assert result["status"] == "empty"
    assert result["queued"] == 0
    assert result["pending_tasks"] == 0
    assert result["skipped"] == 1


def test_start_slice_scan_does_not_requeue_existing_marker(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260524-12-57-08.mp4"
    source.write_bytes(b"mp4")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    result = slice_control.start_slice_scan(videos_root=videos)

    assert result["status"] == "queued"
    assert result["queued"] == 0
    assert result["pending_tasks"] == 1
    assert result["skipped"] == 1


def test_start_slice_scan_reports_existing_pending_tasks(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260524-12-57-08.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )

    result = slice_control.start_slice_scan(videos_root=videos)

    assert result["status"] == "queued"
    assert result["queued"] == 0
    assert result["pending_tasks"] == 1


def test_start_slice_scan_writes_slice_options_in_marker(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260524-12-57-08.mp4"
    source.write_bytes(b"mp4")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")

    result = slice_control.start_slice_scan(
        videos_root=videos,
        slice_options={"burst_ratio": 3.0, "burst_top_n": 2},
    )

    marker = json.loads(source.with_suffix(".mp4.pending").read_text(encoding="utf-8"))
    assert result["queued"] == 1
    assert marker["slice_options"]["burst_ratio"] == 3.0
    assert marker["slice_options"]["burst_top_n"] == 2


def test_start_slice_scan_skips_source_recordings_below_min_size(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260524-12-57-08.mp4"
    source.write_bytes(b"x" * (20 * 1024 * 1024))
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    monkeypatch.setattr(slice_control, "MIN_SOURCE_RECORDING_SIZE_MB", 100, raising=False)

    result = slice_control.start_slice_scan(videos_root=videos)

    assert result["status"] == "empty"
    assert result["queued"] == 0
    assert result["pending_tasks"] == 0
    assert result["skipped"] == 1
    assert not source.with_suffix(".mp4.pending").exists()
