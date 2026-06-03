"""Tests for src/burn/task_history.py."""

from src.burn.task_history import write_task_history, read_task_history


def test_write_and_read_task_history_success(tmp_path):
    source = tmp_path / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")

    written = write_task_history(
        source,
        status="done",
        started_at="2026-06-02T12:00:00",
        finished_at="2026-06-02T12:31:00",
        worker_pid=1234,
        slice_count=3,
        output_slices=["22384516/3488s_22384516_20260527-12-55-32.mp4"],
    )

    assert written.exists()
    assert written.suffix == ".json"

    data = read_task_history(source)
    assert data is not None
    assert data["status"] == "done"
    assert data["worker_pid"] == 1234
    assert data["slice_count"] == 3
    assert len(data["output_slices"]) == 1


def test_write_and_read_task_history_failed(tmp_path):
    source = tmp_path / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")

    write_task_history(
        source,
        status="failed",
        error="No danmaku file",
    )

    data = read_task_history(source)
    assert data is not None
    assert data["status"] == "failed"
    assert data["error"] == "No danmaku file"


def test_read_task_history_returns_none_when_missing(tmp_path):
    source = tmp_path / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")

    assert read_task_history(source) is None


def test_task_history_includes_timestamps(tmp_path):
    source = tmp_path / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")

    write_task_history(source, status="done")

    data = read_task_history(source)
    assert data is not None
    assert "started_at" in data
    assert "finished_at" in data


def test_task_history_uses_explicit_videos_root_for_relative_path(tmp_path, monkeypatch):
    videos = tmp_path / "CustomVideos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    monkeypatch.delenv("BILIVE_VIDEOS_DIR", raising=False)

    write_task_history(source, status="done", videos_root=videos)

    data = read_task_history(source)
    assert data is not None
    assert data["source_rel_path"] == "22384516/22384516_20260527-12-55-32.mp4"


def test_task_history_persists_segments(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")

    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg1",
                "judge_status": "judge_failed",
                "judge_error": "LLM failed: 502",
            }
        ],
    )

    data = read_task_history(source)
    assert data is not None
    assert data["segments"] == [
        {
            "segment_id": "seg1",
            "judge_status": "judge_failed",
            "judge_error": "LLM failed: 502",
        }
    ]
