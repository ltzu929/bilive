from datetime import datetime, timezone
import json

from src.burn.task_history import write_task_history
from src.dashboard.source_lifecycle import (
    default_recording_state,
    mutate_recording_state,
    read_recording_state,
)
from src.dashboard.task_state import build_task_inventory
from src.maintenance.recording_retention import maintain_recording_retention
from src.server.action_jobs import enqueue_action_job, find_active_recording_job


def _source(videos):
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"source")
    source.with_suffix(".xml").write_text("<i/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    write_task_history(source, status="done", videos_root=videos, segments=[])
    return source


def _set_retention_window(videos, task_id, source_rel_path, room_id, start):
    state = default_recording_state(task_id, source_rel_path, room_id)
    state["retention_started_at"] = datetime.fromtimestamp(
        start, timezone.utc
    ).isoformat()
    state["retention_deadline"] = datetime.fromtimestamp(
        start + 14 * 86400, timezone.utc
    ).isoformat()
    mutate_recording_state(
        videos,
        task_id,
        lambda _current: state,
        source_rel_path=source_rel_path,
        room_id=room_id,
    )


def test_retention_warns_on_day_11_and_enqueues_day_14_recycle(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    task = build_task_inventory(videos)[0]
    start = 1_000_000.0
    _set_retention_window(
        videos,
        task["task_id"],
        task["source_rel_path"],
        task["room_id"],
        start,
    )

    warning = maintain_recording_retention(
        videos,
        now=start + 11 * 86400,
    )
    assert [item["task_id"] for item in warning["warnings"]] == [task["task_id"]]
    assert warning["scheduled"] == []

    scheduled = maintain_recording_retention(
        videos,
        now=start + 14 * 86400,
    )
    assert scheduled["warnings"] == []
    assert len(scheduled["scheduled"]) == 1
    job = find_active_recording_job(videos, task["task_id"])
    assert job is not None
    assert job["action"] == "trash_recording"
    assert read_recording_state(videos, task["task_id"])["review_state"] == "trash_pending"
    assert json.loads(
        (videos / ".bilive-jobs" / f"{job['job_id']}.pending.json").read_text(
            encoding="utf-8"
        )
    )["recording_id"] == task["task_id"]


def test_retention_enqueues_without_draining_unrelated_action_jobs(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    task = build_task_inventory(videos)[0]
    start = 1_000_000.0
    _set_retention_window(
        videos,
        task["task_id"],
        task["source_rel_path"],
        task["room_id"],
        start,
    )
    unrelated = enqueue_action_job(
        videos,
        action="finalize_segment",
        segment_id="segment-1",
    )["job"]
    result = maintain_recording_retention(
        videos,
        now=start + 14 * 86400,
    )

    assert (videos / ".bilive-jobs" / f"{unrelated['job_id']}.pending.json").is_file()
    trash_job_id = result["scheduled"][0]["job_id"]
    assert (videos / ".bilive-jobs" / f"{trash_job_id}.pending.json").is_file()


def test_retention_keeps_reason_when_active_recording_action_blocks_recycle(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    task = build_task_inventory(videos)[0]
    start = 1_000_000.0
    _set_retention_window(
        videos,
        task["task_id"],
        task["source_rel_path"],
        task["room_id"],
        start,
    )
    enqueue_action_job(
        videos,
        action="trash_recording",
        recording_id=task["task_id"],
    )

    result = maintain_recording_retention(
        videos,
        now=start + 14 * 86400,
    )

    assert result["scheduled"] == []
    assert result["blocked"] == [
        {
            "task_id": task["task_id"],
            "reason": "trash_action_active",
            "job_id": find_active_recording_job(videos, task["task_id"])["job_id"],
        }
    ]
    state = read_recording_state(videos, task["task_id"])
    assert state["trash_status"] == "blocked"
    assert state["trash_block_reason"] == "trash_action_active"
