import json
from pathlib import Path

import pytest

from src.burn.task_history import write_task_history
from src.dashboard import recording_trash
from src.dashboard import source_lifecycle
from src.dashboard.task_state import build_task_inventory
from src.db import conn


def _recording(videos: Path):
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"source")
    source.with_suffix(".flv").write_bytes(b"flv")
    source.with_suffix(".xml").write_text("<i/>", encoding="utf-8")
    source.with_suffix(".ass").write_text("ass", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("stale", encoding="utf-8")
    source.with_suffix(".mp4.pending").unlink()
    return source


def _state(videos: Path, source: Path):
    task = build_task_inventory(videos)[0]
    source_lifecycle.set_review_state(
        videos,
        task["task_id"],
        "review_complete",
        source_rel_path=task["source_rel_path"],
        room_id=task["room_id"],
    )
    return task["task_id"]


def test_trash_plan_protects_final_output_and_upload_metadata(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _recording(videos)
    final = source.with_name("20s_final.mp4")
    final.write_bytes(b"final")
    upload_metadata = final.with_suffix(".upload.json")
    upload_metadata.write_text("{}", encoding="utf-8")
    intermediate = source.with_name("10s_source_context.mp4")
    intermediate.write_bytes(b"intermediate")
    intermediate.with_name(intermediate.stem + "_analysis.json").write_text(
        "{}", encoding="utf-8"
    )
    task_id = build_task_inventory(videos)[0]["task_id"]
    history = {
        "status": "done",
        "segments": [
            {
                "segment_id": "seg1",
                "candidate_path": str(final),
                "candidate_rel_path": final.relative_to(videos).as_posix(),
                "judge_status": "manual_keep",
                "upload_status": "awaiting_publish",
                "artifacts": {
                    "final_output": {
                        "rel_path": final.relative_to(videos).as_posix(),
                    }
                },
            }
        ],
    }
    write_task_history(source, status="done", videos_root=videos, segments=history["segments"])
    history_path = source.with_suffix(".mp4.task.json")
    stored_history = json.loads(history_path.read_text(encoding="utf-8"))
    stored_history["candidate_judgments"] = [
        {
            "candidate_path": str(intermediate),
            "candidate_start_seconds": 10,
            "candidate_end_seconds": 20,
        }
    ]
    history_path.write_text(
        json.dumps(stored_history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)
    conn.stage_upload_queue(str(final), db_path=db_path)
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(db_path))
    source_lifecycle.set_review_state(
        videos,
        task_id,
        "review_complete",
        source_rel_path=source.relative_to(videos).as_posix(),
        room_id="22384516",
    )

    plan = recording_trash.build_trash_plan(videos, task_id)

    paths = set(plan["files"])
    assert "22384516/20s_final.mp4" not in paths
    assert "22384516/20s_final.upload.json" not in paths
    assert "22384516/10s_source_context.mp4" in paths
    assert "22384516/10s_source_context_analysis.json" in paths
    assert "22384516/22384516_20260602-12-56-49.mp4" in paths
    assert "22384516/22384516_20260602-12-56-49.mp4.task.json" in paths


def test_trash_recording_uses_injected_reversible_mover_and_is_idempotent(tmp_path):
    videos = tmp_path / "Videos"
    source = _recording(videos)
    task_id = _state(videos, source)
    moved: list[list[Path]] = []

    result = recording_trash.trash_recording(
        videos,
        task_id,
        mover=lambda paths: moved.append(paths),
    )

    assert result["status"] == "trashed"
    assert moved and source in moved[0]
    state = source_lifecycle.read_recording_state(videos, task_id)
    assert state["trash_status"] == "done"
    assert state["trash_files"]
    log = (videos / ".bilive-state" / "trash-log.jsonl").read_text(encoding="utf-8")
    assert json.loads(log.splitlines()[0])["status"] == "completed"

    second = recording_trash.trash_recording(
        videos,
        task_id,
        mover=lambda _paths: pytest.fail("idempotent trash must not move again"),
    )
    assert second["status"] == "already_trashed"
    assert second["idempotent"] is True


def test_trash_plan_blocks_active_segment_job(tmp_path):
    videos = tmp_path / "Videos"
    source = _recording(videos)
    task = build_task_inventory(videos)[0]
    candidate = source.with_name("10s_candidate.mp4")
    candidate.write_bytes(b"candidate")
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg1",
                "candidate_path": str(candidate),
                "candidate_rel_path": candidate.relative_to(videos).as_posix(),
                "judge_status": "drop",
                "upload_status": "not_queued",
            }
        ],
    )
    source_lifecycle.set_review_state(
        videos,
        task["task_id"],
        "review_complete",
        source_rel_path=task["source_rel_path"],
        room_id=task["room_id"],
    )
    from src.server.action_jobs import enqueue_action_job

    enqueue_action_job(videos, action="render_segment", segment_id="seg1")

    with pytest.raises(source_lifecycle.RecordingTrashBlocked) as error:
        recording_trash.build_trash_plan(videos, task["task_id"])

    assert "segment_action_active:seg1" in error.value.blockers


def test_trash_plan_blocks_unknown_segment_action_state(tmp_path):
    videos = tmp_path / "Videos"
    source = _recording(videos)
    task = build_task_inventory(videos)[0]
    candidate = source.with_name("10s_candidate.mp4")
    candidate.write_bytes(b"candidate")
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg1",
                "candidate_path": str(candidate),
                "candidate_rel_path": candidate.relative_to(videos).as_posix(),
                "judge_status": "drop",
                "upload_status": "not_queued",
                "action_state": {"action": "render_segment", "status": "processing"},
            }
        ],
    )
    source_lifecycle.set_review_state(
        videos,
        task["task_id"],
        "review_complete",
        source_rel_path=task["source_rel_path"],
        room_id=task["room_id"],
    )

    with pytest.raises(source_lifecycle.RecordingTrashBlocked) as error:
        recording_trash.build_trash_plan(videos, task["task_id"])

    assert "segment_action_state_active:seg1" in error.value.blockers
