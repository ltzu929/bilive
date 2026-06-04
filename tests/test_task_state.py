"""Tests for src/dashboard/task_state.py - Task inventory and status model."""

import json
import time
import base64

import pytest

from src.dashboard import task_state
from src.burn.task_history import write_task_history


def test_build_task_inventory_returns_ready_state(tmp_path):
    """Source with .mp4 + .xml, no pending/done → ready."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert len(tasks) == 1
    t = tasks[0]
    assert t["status"] == "ready"
    assert t["room_id"] == "22384516"
    assert t["source_name"] == "22384516_20260527-12-55-32.mp4"
    assert t["source_rel_path"] == "22384516/22384516_20260527-12-55-32.mp4"
    assert t["task_id"]  # task_id is base64 of source_rel_path
    assert "=" not in t["task_id"]
    assert task_state.resolve_task_id(videos, t["task_id"]) == source.resolve()
    assert t["has_xml"] is True
    assert t["pending_path"] is None
    assert t["done_path"] is None


def test_build_task_inventory_returns_pending_state(tmp_path):
    """Source with .mp4.pending → pending."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    pending = source.with_suffix(".mp4.pending")
    pending.write_text(json.dumps({"video_rel_path": "22384516/22384516_20260527-12-55-32.mp4"}), encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["pending_path"] == "22384516/22384516_20260527-12-55-32.mp4.pending"


def test_build_task_inventory_returns_done_state(tmp_path):
    """Source with .mp4.done → done."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert len(tasks) == 1
    assert tasks[0]["status"] == "done"
    assert tasks[0]["done_path"] == "22384516/22384516_20260527-12-55-32.mp4.done"


def test_done_task_shows_skipped_history_message(tmp_path):
    """Done marker plus skipped history should keep the task done but explain why."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    write_task_history(
        source,
        status="skipped",
        diagnostics=[
            {
                "id": "result",
                "title": "切片结果",
                "status": "warning",
                "message": "录像小于切片阈值，已跳过",
                "details": [],
            }
        ],
        videos_root=videos,
    )

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert tasks[0]["status"] == "done"
    assert tasks[0]["message"] == "录像小于切片阈值，已跳过"


def test_done_task_shows_zero_slice_history_message(tmp_path):
    """Done marker plus 0-slice diagnostics should explain that no clips were made."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    write_task_history(
        source,
        status="done",
        diagnostics=[
            {
                "id": "result",
                "title": "切片结果",
                "status": "warning",
                "message": "生成 0 个切片",
                "details": [{"label": "切片数", "value": "0"}],
            }
        ],
        videos_root=videos,
    )

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert tasks[0]["status"] == "done"
    assert tasks[0]["message"] == "生成 0 个切片"


def test_build_task_inventory_returns_failed_from_history(tmp_path):
    """Failed task history is visible after watcher removes .pending."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    write_task_history(source, status="failed", error="slice failed", videos_root=videos)

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert tasks[0]["status"] == "failed"
    assert tasks[0]["message"] == "slice failed"


def test_pending_marker_overrides_old_failed_history(tmp_path):
    """Requeued failed tasks should show pending, not the previous failure."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")
    write_task_history(source, status="failed", error="old failure", videos_root=videos)

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert tasks[0]["status"] == "pending"
    assert tasks[0]["message"] == "已排队，等待 PC worker"


def test_build_task_inventory_returns_skipped_when_no_xml(tmp_path):
    """Source without .xml → skipped."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert len(tasks) == 1
    assert tasks[0]["status"] == "skipped"
    assert tasks[0]["has_xml"] is False


def test_build_task_inventory_skips_slice_output(tmp_path):
    """Slice output files (e.g. 120s_...) are not listed as tasks."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    slice_out = room / "120s_22384516_20260527-12-55-32.mp4"
    slice_out.write_bytes(b"slice data")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert len(tasks) == 0


def test_build_task_inventory_filters_by_room_id(tmp_path):
    """GET /api/tasks?room_id filters to one room."""
    videos = tmp_path / "Videos"
    room_a = videos / "11111"
    room_a.mkdir(parents=True)
    (room_a / "11111_20260527-12-00-00.mp4").write_bytes(b"a")
    (room_a / "11111_20260527-12-00-00.xml").write_text("<x/>", encoding="utf-8")
    room_b = videos / "22222"
    room_b.mkdir(parents=True)
    (room_b / "22222_20260527-12-00-00.mp4").write_bytes(b"b")
    (room_b / "22222_20260527-12-00-00.xml").write_text("<x/>", encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos, room_id="11111")

    assert len(tasks) == 1
    assert tasks[0]["room_id"] == "11111"


def test_build_task_inventory_includes_source_size(tmp_path):
    """Task includes source_size_mb."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"x" * (5 * 1024 * 1024))  # 5 MB
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert tasks[0]["source_size_mb"] == pytest.approx(5.0, abs=0.1)


def test_build_task_inventory_includes_updated_at_timestamp(tmp_path):
    """Task includes updated_at from source file mtime."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")

    tasks = task_state.build_task_inventory(videos_root=videos)

    assert isinstance(tasks[0]["updated_at"], float)
    assert tasks[0]["updated_at"] > 0


def test_load_pending_queue_state_unchanged(tmp_path):
    """Existing load_pending_queue_state still works after refactor."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260527-12-55-32.mp4.pending").write_text("{}", encoding="utf-8")

    from src.dashboard.slice_control import load_pending_queue_state
    state = load_pending_queue_state(videos)

    assert state["pending_tasks"] == 1


def test_resolve_task_id_accepts_unpadded_base64_with_mod_three_length(tmp_path):
    """Padding restoration handles IDs whose stripped length is 3 mod 4."""
    videos = tmp_path / "Videos"
    room = videos / "1"
    room.mkdir(parents=True)
    source = room / "ab.mp4"
    source.write_bytes(b"video")
    rel = "1/ab.mp4"
    task_id = base64.urlsafe_b64encode(rel.encode("utf-8")).decode("ascii").rstrip("=")
    assert len(task_id) % 4 == 3

    assert task_state.resolve_task_id(videos, task_id) == source.resolve()
