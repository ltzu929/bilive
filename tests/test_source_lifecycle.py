import json
from pathlib import Path

import pytest

from src.burn.task_history import write_task_history
from src.dashboard import source_workbench
from src.dashboard import source_lifecycle
from src.dashboard.source_lifecycle import (
    build_lifecycle_view,
    default_recording_state,
    generate_streamer_recommendation,
    append_experience,
    mutate_recording_state,
    patch_streamer_profile,
    read_experiences,
    read_recording_state,
    read_streamer_profile,
    set_review_state,
)
from src.dashboard.task_state import build_task_inventory
from src.db import conn


def _source(videos: Path):
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"source")
    source.with_suffix(".xml").write_text("<i/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    return source


def _history(source: Path, videos: Path, segments=None):
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=list(segments or []),
    )


def _keep_segment(source: Path, videos: Path, segment_id="seg1"):
    candidate = source.with_name("10s_candidate.mp4")
    candidate.write_bytes(b"candidate")
    return {
        "segment_id": segment_id,
        "candidate_path": str(candidate),
        "candidate_rel_path": candidate.relative_to(videos).as_posix(),
        "start_seconds": 10,
        "end_seconds": 20,
        "judge_status": "keep",
        "upload_status": "not_queued",
        "transcript": "a useful line",
    }


def test_finalize_stages_until_explicit_publish_approval(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _source(videos)
    _history(source, videos, [_keep_segment(source, videos)])
    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(db_path))
    monkeypatch.setattr(
        source_workbench,
        "slice_video",
        lambda _source, output, _start, _duration: output.write_bytes(b"raw"),
    )
    monkeypatch.setattr(
        source_workbench,
        "transcribe_segment_audio",
        lambda _path, _duration: {
            "transcript": "a useful line",
            "segments": [{"start": 0, "end": 1, "text": "a useful line"}],
        },
    )
    def fake_burn(_raw, _analysis, output, _style):
        output.write_bytes(b"final")
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(source_workbench, "burn_final_subtitles", fake_burn)
    monkeypatch.setattr(source_workbench, "write_slice_upload_metadata", lambda *_a, **_k: None)

    task_id = build_task_inventory(videos)[0]["task_id"]
    source_workbench.prepare_segment_finalize(videos, "seg1", {})
    staged = source_workbench.finalize_segment(videos, "seg1")

    assert staged["upload_status"] == "awaiting_publish"
    assert staged["publish_approval"] == ""
    assert conn.peek_next_upload(db_path) is None

    old_final = staged["candidate_path"]
    changed = source_workbench.prepare_segment_finalize(
        videos,
        "seg1",
        {"start_seconds": 12, "end_seconds": 22},
    )
    assert changed["upload_status"] == "not_queued"
    assert changed["publish_approval"] == ""
    assert conn.peek_next_upload(db_path) is None
    assert old_final != str(videos / changed["artifacts"]["final_output"]["rel_path"])

    staged = source_workbench.finalize_segment(videos, "seg1")
    assert staged["upload_status"] == "awaiting_publish"
    assert conn.peek_next_upload(db_path) is None

    approved = source_workbench.approve_publish_segment(videos, "seg1")
    assert approved["upload_status"] == "queued"
    assert approved["publish_approval"] == "approved"
    assert conn.peek_next_upload(db_path)["video_path"] == approved["candidate_path"]

    repeated = source_workbench.approve_publish_segment(videos, "seg1")
    assert repeated["publish_approval"] == "approved"
    assert repeated["publish_idempotent"] is True
    assert len(conn.list_upload_queue(db_path)) == 1


def test_zero_candidate_requires_explicit_whole_recording_confirmation(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    _history(source, videos)
    task_id = build_task_inventory(videos)[0]["task_id"]

    with pytest.raises(source_workbench.SegmentStateConflict, match="零候选"):
        source_workbench.prepare_source_review_completion(videos, task_id)

    completed = source_workbench.prepare_source_review_completion(
        videos,
        task_id,
        confirmed_no_content=True,
    )
    assert completed["review_state"] == "review_complete"
    records = read_experiences(videos, room_id="22384516")
    assert records[0]["experience_type"] == "recording_no_content"


def test_technical_failure_dropped_after_review_is_not_negative_content_sample(tmp_path):
    records = source_lifecycle.record_review_experiences(
        tmp_path / "Videos",
        room_id="22384516",
        task_id="recording-1",
        source_rel_path="22384516/source.mp4",
        segments=[
            {
                "segment_id": "seg1",
                "judge_status": "drop",
                "_technical_failure": True,
                "failure": {
                    "stage": "judge",
                    "code": "judge_failed",
                    "summary": "MiMo unavailable",
                    "technical_details": "HTTP 503",
                },
            }
        ],
    )

    assert records[0]["experience_type"] == "technical_failure"
    assert records[0]["conclusion"] == "technical_failure"
    assert records[0]["reason_type"] == "judge:judge_failed"
    assert not any(item["experience_type"] == "negative" for item in records)


def test_review_experience_preserves_bounded_analysis_and_danmaku_evidence(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    source.with_suffix(".xml").write_text(
        '<i><d p="12,1,25,16711680,0,0,0,0">弹幕证据</d></i>',
        encoding="utf-8",
    )
    analysis = source.with_name("10s_candidate_analysis.json")
    analysis.write_text(
        json.dumps({"transcript": "主播的转录证据"}, ensure_ascii=False),
        encoding="utf-8",
    )
    records = source_lifecycle.record_review_experiences(
        videos,
        room_id="22384516",
        task_id="recording-1",
        source_rel_path=source.relative_to(videos).as_posix(),
        segments=[
            {
                "segment_id": "seg1",
                "judge_status": "keep",
                "start_seconds": 10,
                "end_seconds": 20,
                "danmaku_count": 1,
                "artifacts": {
                    "analysis_sidecar": {
                        "rel_path": analysis.relative_to(videos).as_posix(),
                    }
                },
            }
        ],
    )

    assert records[0]["transcript_summary"] == "主播的转录证据"
    assert records[0]["danmaku_summary"] == {
        "count": 1,
        "text": "弹幕证据",
    }


def test_streamer_evidence_summary_and_recommendation_basis_are_explicit(tmp_path):
    videos = tmp_path / "Videos"
    for index in range(4):
        append_experience(
            videos,
            {
                "room_id": "22384516",
                "task_id": f"positive-{index}",
                "source_rel_path": f"22384516/positive-{index}.mp4",
                "start_seconds": 10,
                "end_seconds": 20,
                "experience_type": "positive",
                "conclusion": "positive",
                "reason_type": "content_review",
                "note": "保留",
                "dedupe_key": f"positive-{index}",
            },
        )
    append_experience(
        videos,
        {
            "room_id": "22384516",
            "task_id": "negative-1",
            "source_rel_path": "22384516/negative-1.mp4",
            "start_seconds": 30,
            "end_seconds": 40,
            "experience_type": "negative",
            "conclusion": "negative",
            "reason_type": "boundary_incomplete",
            "note": "边界不完整",
            "dedupe_key": "negative-1",
        },
    )

    summary = source_lifecycle.streamer_evidence_summary(videos, "22384516")
    assert summary["evidence_status"] == "ready"
    assert summary["sample_size"] == 5
    recommendation_state = generate_streamer_recommendation(videos, "22384516")
    recommendation = recommendation_state["recommendations"][-1]
    assert recommendation["evidence_status"] == "ready"
    assert recommendation["basis"][0]["task_id"] == "positive-0"
    assert recommendation["basis"][-1]["decision"] == "negative"
    assert recommendation["basis"][-1]["source_rel_path"] == (
        "22384516/negative-1.mp4"
    )


def test_streamer_profile_defaults_are_isolated_and_recommendation_needs_evidence(tmp_path):
    videos = tmp_path / "Videos"
    profile = patch_streamer_profile(
        videos,
        "22384516",
        {
            "display_name": "主播 A",
            "aliases": ["A"],
            "default_tags": ["A风格"],
            "default_slice_options": {"burst_top_n": 2},
            "default_subtitle_style": {"font_name": "Noto Sans SC", "font_size": 24},
            "approved_guidance": "保留完整落点",
        },
    )
    assert profile["display_name"] == "主播 A"
    assert read_streamer_profile(videos, "22384516")["default_tags"] == ["A风格"]
    assert read_streamer_profile(videos, "22966160")["default_tags"] == []
    insufficient = generate_streamer_recommendation(videos, "22384516")
    assert insufficient["evidence_status"] == "insufficient_evidence"
    assert "证据不足" in insufficient["message"]


def test_lifecycle_retention_warning_and_expiry_are_exposed(tmp_path):
    videos = tmp_path / "Videos"
    source = _source(videos)
    _history(source, videos)
    task = build_task_inventory(videos)[0]
    state = default_recording_state(
        task["task_id"],
        task["source_rel_path"],
        task["room_id"],
    )
    started = 1_000_000
    state["retention_started_at"] = "1970-01-12T13:46:40+00:00"
    state["retention_deadline"] = "1970-01-26T13:46:40+00:00"
    mutate_recording_state(
        videos,
        task["task_id"],
        lambda _current: state,
        source_rel_path=task["source_rel_path"],
        room_id=task["room_id"],
    )

    warning = build_lifecycle_view(
        videos,
        task,
        {"status": "done", "segments": []},
        [],
        now=started + 11 * 86400,
    )
    assert warning["retention_warning"] is True
    assert warning["trash_eligible"] is False

    expired = build_lifecycle_view(
        videos,
        task,
        {"status": "done", "segments": []},
        [],
        now=started + 14 * 86400,
    )
    assert expired["retention_expired"] is True
    assert expired["trash_eligible"] is True

    set_review_state(
        videos,
        task["task_id"],
        "review_complete",
        source_rel_path=task["source_rel_path"],
        room_id=task["room_id"],
    )
    reviewed = build_lifecycle_view(
        videos,
        task,
        {"status": "done", "segments": []},
        [],
        now=started + 11 * 86400,
    )
    assert reviewed["retention_warning"] is False
