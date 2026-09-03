import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.autoslice.analysis_result import AnalysisResult
from src.burn.task_history import write_task_history
from src.dashboard import source_workbench
from src.dashboard.task_state import build_task_inventory


def _write_danmaku_xml(path):
    path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<i>\n"
        "  <d p=\"1,1,25,16777215,0,0,0,0\">a</d>\n"
        "  <d p=\"2,1,25,16777215,0,0,0,0\">b</d>\n"
        "  <d p=\"11,1,25,16777215,0,0,0,0\">c</d>\n"
        "  <d p=\"21,1,25,16777215,0,0,0,0\">d</d>\n"
        "  <d p=\"29,1,25,16777215,0,0,0,0\">e</d>\n"
        "</i>\n",
        encoding="utf-8",
    )


def _create_processed_source(videos, *, failed_preview=False):
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"video")
    _write_danmaku_xml(source.with_suffix(".xml"))
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    (room / "10s_22384516_20260602-12-56-49.mp4").write_bytes(b"keep")
    (room / "40s_22384516_20260602-12-56-49.mp4").write_bytes(b"failed")
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg_keep",
                "source_rel_path": "22384516/22384516_20260602-12-56-49.mp4",
                "candidate_path": str(room / "10s_22384516_20260602-12-56-49.mp4"),
                "candidate_rel_path": "22384516/10s_22384516_20260602-12-56-49.mp4",
                "start_seconds": 10.0,
                "end_seconds": 70.0,
                "judge_status": "keep",
                "upload_status": "queued",
            },
            {
                "segment_id": "seg_failed",
                "source_rel_path": "22384516/22384516_20260602-12-56-49.mp4",
                "candidate_path": str(room / "40s_22384516_20260602-12-56-49.mp4"),
                "candidate_rel_path": "22384516/40s_22384516_20260602-12-56-49.mp4",
                "start_seconds": 40.0,
                "end_seconds": 100.0,
                "judge_status": "judge_failed",
                "judge_error": "LLM failed",
                "upload_status": "not_queued",
                "preview_available": failed_preview,
            },
        ],
    )
    return source


def test_source_recording_detail_returns_density_and_segments(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    task_id = build_task_inventory(videos)[0]["task_id"]

    detail = source_workbench.build_source_recording_detail(videos, task_id)

    assert detail["source_name"] == source.name
    assert detail["source_media_id"]
    assert detail["density_points"] == [
        {"start_seconds": 0, "end_seconds": 10, "count": 2, "normalized": 1.0},
        {"start_seconds": 10, "end_seconds": 20, "count": 1, "normalized": 0.5},
        {"start_seconds": 20, "end_seconds": 30, "count": 2, "normalized": 1.0},
    ]
    assert detail["segments"][1]["judge_status"] == "judge_failed"
    assert detail["segments"][1]["candidate_media_id"] == ""
    assert detail["segments"][1]["preview_available"] is False
    assert detail["segments"][1]["preview_reason"] == "LLM failed"
    assert detail["segments"][1]["quality"]["reason"] == ""
    assert detail["segments"][1]["failure"] == {
        "stage": "judge",
        "code": "judge_failed",
        "summary": "LLM failed",
        "technical_details": "LLM failed",
        "recovery_action": "重新分析，或人工调整后生成成片",
    }
    assert detail["segments"][1]["artifacts"]["raw_candidate"]["exists"] is True
    assert detail["segments"][1]["artifacts"]["final_output"]["exists"] is False
    assert detail["segments"][1]["timings_ms"] == {}
    assert detail["segments"][1]["action_state"]["status"] == "idle"


def test_source_recording_detail_rejects_stale_failed_preview_and_final_output(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos, failed_preview=True)
    history_path = source.with_suffix(".mp4.task.json")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["segments"][1]["artifacts"] = {
        "final_output": {
            "rel_path": history["segments"][1]["candidate_rel_path"],
        }
    }
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    task_id = build_task_inventory(videos)[0]["task_id"]

    detail = source_workbench.build_source_recording_detail(videos, task_id)
    failed = detail["segments"][1]

    assert failed["judge_status"] == "judge_failed"
    assert failed["preview_available"] is False
    assert failed["candidate_media_id"] == ""
    assert failed["artifacts"]["raw_candidate"]["exists"] is True
    assert failed["artifacts"]["final_output"]["exists"] is False
    assert "media_id" not in failed["artifacts"]["final_output"]


def test_source_recording_detail_is_read_only(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    task_id = build_task_inventory(videos)[0]["task_id"]
    history_path = source.with_suffix(".mp4.task.json")
    before_history = history_path.read_bytes()
    before_paths = sorted(
        path.relative_to(videos).as_posix() for path in videos.rglob("*")
    )

    source_workbench.build_source_recording_detail(videos, task_id)

    assert history_path.read_bytes() == before_history
    assert sorted(
        path.relative_to(videos).as_posix() for path in videos.rglob("*")
    ) == before_paths
    assert not (source.parent / ".bilive-artifacts").exists()


def test_source_recording_list_counts_keep_and_judge_failed(tmp_path):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)

    items = source_workbench.build_source_recording_list(videos)

    assert len(items) == 1
    assert items[0]["summary_counts"]["keep"] == 1
    assert items[0]["summary_counts"]["judge_failed"] == 1
    assert items[0]["segment_count"] == 2


def test_candidate_relative_path_cannot_escape_videos_root(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    segment = {
        "candidate_rel_path": "../outside.mp4",
        "candidate_path": str(outside),
    }

    assert source_workbench._candidate_rel_path(videos.resolve(), segment) == ""
    with pytest.raises(ValueError, match="outside Videos root"):
        source_workbench._segment_candidate_path(videos.resolve(), segment)


def test_manual_keep_segment_marks_candidate_without_queueing_upload(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    queued = []
    metadata = []

    monkeypatch.setattr(source_workbench, "insert_upload_queue", lambda path: queued.append(path) or True)
    monkeypatch.setattr(
        source_workbench,
        "write_slice_upload_metadata",
        lambda path, **kwargs: metadata.append((path, kwargs)) or source.with_suffix(".upload.json"),
    )

    updated = source_workbench.manual_keep_segment(
        videos,
        "seg_keep",
        {
            "title": "Manual title",
            "description": "Manual desc",
            "tags": ["live", "clip"],
        },
    )

    assert updated["judge_status"] == "manual_keep"
    assert updated["manual_override"] is True
    assert updated["upload_status"] == "not_queued"
    assert queued == []
    assert metadata == []
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][0]["judge_status"] == "manual_keep"


def test_manual_keep_segment_does_not_report_queue_failure(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    metadata = []

    monkeypatch.setattr(source_workbench, "insert_upload_queue", lambda path: False)
    monkeypatch.setattr(
        source_workbench,
        "write_slice_upload_metadata",
        lambda path, **kwargs: metadata.append((path, kwargs)) or source.with_suffix(".upload.json"),
    )
    # Re-check confirms the row is not in the queue, so False is a real failure.
    monkeypatch.setattr(source_workbench, "get_upload_item", lambda path: None)

    updated = source_workbench.manual_keep_segment(videos, "seg_keep")

    assert updated["judge_status"] == "manual_keep"
    assert updated["manual_override"] is True
    assert updated["upload_status"] == "not_queued"
    assert "upload_error" not in updated
    assert metadata == []
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][0]["upload_status"] == "not_queued"


def test_manual_keep_segment_is_idempotent_before_finalization(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    metadata = []

    # Legacy queue hooks are intentionally unused: manual keep only records
    # the human decision; finalization creates the staged row later.
    monkeypatch.setattr(source_workbench, "insert_upload_queue", lambda path: False)
    monkeypatch.setattr(
        source_workbench,
        "write_slice_upload_metadata",
        lambda path, **kwargs: metadata.append((path, kwargs)) or source.with_suffix(".upload.json"),
    )
    monkeypatch.setattr(
        source_workbench,
        "get_upload_item",
        lambda path: {"video_path": str(path), "status": "queued"},
    )

    updated = source_workbench.manual_keep_segment(videos, "seg_keep")

    assert updated["judge_status"] == "manual_keep"
    assert updated["upload_status"] == "not_queued"
    assert "upload_error" not in updated
    assert metadata == []
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][0]["upload_status"] == "not_queued"


def test_manual_keep_segment_rejects_stale_failed_preview(tmp_path):
    videos = tmp_path / "Videos"
    _create_processed_source(videos, failed_preview=True)

    with pytest.raises(ValueError, match="内部候选没有可发布预览"):
        source_workbench.manual_keep_segment(videos, "seg_failed")


def test_finalize_segment_separates_artifacts_and_queues_after_success(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    calls = {"asr": 0, "metadata": [], "queue": []}

    def fake_slice(_source, output, start, duration):
        assert (start, duration) == (42.0, 18.0)
        output.write_bytes(b"raw")

    def fake_asr(path, duration):
        calls["asr"] += 1
        assert Path(path).read_bytes() == b"raw"
        assert duration == 18.0
        return {
            "transcript": "完整的一句话",
            "segments": [{"start": 0.0, "end": 2.0, "text": "完整的一句话"}],
        }

    def fake_burn(raw_path, analysis, output_path, style):
        assert raw_path != output_path
        assert analysis.transcript == "完整的一句话"
        output_path.write_bytes(b"final")
        return SimpleNamespace(burned=True, message="ok")

    def fake_activate(path):
        persisted = source_workbench._read_segment(videos, "seg_failed")[2]
        assert persisted["action_state"]["status"] == "done"
        assert persisted["upload_status"] == "awaiting_publish"
        return {"video_path": path, "status": "queued"}

    monkeypatch.setattr(source_workbench, "slice_video", fake_slice)
    monkeypatch.setattr(source_workbench, "transcribe_segment_audio", fake_asr)
    monkeypatch.setattr(source_workbench, "burn_final_subtitles", fake_burn)
    monkeypatch.setattr(
        source_workbench,
        "write_slice_upload_metadata",
        lambda path, **kwargs: calls["metadata"].append((path, kwargs)),
    )
    monkeypatch.setattr(
        source_workbench,
        "stage_upload_queue",
        lambda path: calls["queue"].append(path)
        or {"status": "staged", "created": True},
    )
    monkeypatch.setattr(
        source_workbench,
        "activate_staged_upload",
        fake_activate,
    )

    prepared = source_workbench.prepare_segment_finalize(
        videos,
        "seg_failed",
        {
            "title": "人工确认标题",
            "description": "简介",
            "tags": ["直播", "切片"],
            "start": 42,
            "end": 60,
            "subtitle_style": {"font_size": 26, "margin_v": 80},
        },
    )
    assert prepared["upload_status"] == "not_queued"
    job_id = "a" * 32
    source_workbench.record_segment_action_state(
        videos,
        "seg_failed",
        status="pending",
        job_id=job_id,
    )
    monkeypatch.setattr(
        source_workbench,
        "prepare_segment_finalize",
        lambda *_args, **_kwargs: pytest.fail(
            "revision-guarded jobs must not re-apply prepared edits"
        ),
    )

    updated = source_workbench.finalize_segment(
        videos,
        "seg_failed",
        {
            "_expected_revision": prepared["revision"],
            "_job_id": job_id,
        },
    )

    artifacts = updated["artifacts"]
    raw = videos / artifacts["raw_candidate"]["rel_path"]
    analysis = videos / artifacts["analysis_sidecar"]["rel_path"]
    final = videos / artifacts["final_output"]["rel_path"]
    assert len({raw, analysis, final}) == 3
    assert raw.parent.name == ".bilive-artifacts"
    assert analysis.parent == raw.parent
    assert final.parent == source.parent
    assert raw.read_bytes() == b"raw"
    assert analysis.is_file()
    assert final.read_bytes() == b"final"
    assert updated["candidate_path"] == str(final)
    assert updated["judge_status"] == "manual_keep"
    assert updated["upload_status"] == "awaiting_publish"
    assert updated["failure"] is None
    assert updated["action_state"]["status"] == "done"
    assert set(updated["timings_ms"]) == {
        "raw_render",
        "asr",
        "analysis",
        "subtitle_burn",
        "metadata",
        "queue",
        "total",
    }
    assert calls["asr"] == 1
    assert calls["queue"] == [str(final)]
    assert calls["metadata"][0][1]["title"] == "人工确认标题"


def test_finalize_recovery_accepts_revision_bumped_by_same_validated_job(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)
    prepared = source_workbench.prepare_segment_finalize(
        videos,
        "seg_failed",
        {"title": "prepared"},
    )
    job_id = "b" * 32
    source_workbench.record_segment_action_state(
        videos,
        "seg_failed",
        status="pending",
        job_id=job_id,
    )

    class Interrupted(BaseException):
        pass

    monkeypatch.setattr(
        source_workbench,
        "record_segment_action_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(Interrupted()),
    )
    payload = {
        "_expected_revision": prepared["revision"],
        "_job_id": job_id,
    }
    with pytest.raises(Interrupted):
        source_workbench.finalize_segment(videos, "seg_failed", payload)

    source_workbench._mutate_segment(
        videos,
        "seg_failed",
        lambda _root, _source, segment: segment,
    )

    with pytest.raises(Interrupted):
        source_workbench.finalize_segment(videos, "seg_failed", payload)


def test_finalize_retry_reuses_raw_and_asr_after_subtitle_failure(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    calls = {"slice": 0, "asr": 0, "burn": 0, "queue": 0}

    def fake_slice(_source, output, _start, _duration):
        calls["slice"] += 1
        output.write_bytes(b"raw")

    def fake_asr(_path, _duration):
        calls["asr"] += 1
        return {
            "transcript": "可复用字幕",
            "segments": [{"start": 0.0, "end": 1.0, "text": "可复用字幕"}],
        }

    def fake_burn(_raw, _analysis, output, _style):
        calls["burn"] += 1
        if calls["burn"] == 1:
            return SimpleNamespace(burned=False, message="ffmpeg interrupted")
        output.write_bytes(b"final")
        return SimpleNamespace(burned=True, message="ok")

    monkeypatch.setattr(source_workbench, "slice_video", fake_slice)
    monkeypatch.setattr(source_workbench, "transcribe_segment_audio", fake_asr)
    monkeypatch.setattr(source_workbench, "burn_final_subtitles", fake_burn)
    monkeypatch.setattr(source_workbench, "write_slice_upload_metadata", lambda *a, **k: None)
    monkeypatch.setattr(
        source_workbench,
        "stage_upload_queue",
        lambda _path: calls.__setitem__("queue", calls["queue"] + 1)
        or {"status": "staged", "created": True},
    )
    monkeypatch.setattr(
        source_workbench,
        "activate_staged_upload",
        lambda path: {"video_path": path, "status": "queued"},
    )

    source_workbench.prepare_segment_finalize(videos, "seg_failed", {})
    with pytest.raises(source_workbench.SegmentFinalizeError) as error:
        source_workbench.finalize_segment(videos, "seg_failed")

    assert error.value.failure["stage"] == "subtitle_burn"
    failed = source_workbench._read_segment(videos, "seg_failed")[2]
    assert failed["failure"]["code"] == "subtitle_burn_failed"
    assert failed["artifacts"]["raw_candidate"]["exists"] is True
    assert failed["artifacts"]["analysis_sidecar"]["exists"] is True
    assert failed["artifacts"]["final_output"]["exists"] is False
    assert failed["upload_status"] == "not_queued"
    assert calls == {"slice": 1, "asr": 1, "burn": 1, "queue": 0}

    updated = source_workbench.finalize_segment(videos, "seg_failed")

    assert updated["upload_status"] == "awaiting_publish"
    assert updated["failure"] is None
    assert calls == {"slice": 1, "asr": 1, "burn": 2, "queue": 1}
    assert not source.with_name(f"{source.stem}_reburn_src.mp4").exists()


def test_finalize_honors_skip_upload_queue(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)

    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")
    monkeypatch.setattr(
        source_workbench,
        "slice_video",
        lambda _source, output, _start, _duration: output.write_bytes(b"raw"),
    )
    monkeypatch.setattr(
        source_workbench,
        "transcribe_segment_audio",
        lambda _path, _duration: {
            "transcript": "本地验证",
            "segments": [{"start": 0.0, "end": 1.0, "text": "本地验证"}],
        },
    )
    monkeypatch.setattr(
        source_workbench,
        "burn_final_subtitles",
        lambda _raw, _analysis, output, _style: (
            output.write_bytes(b"final")
            and SimpleNamespace(burned=True, message="ok")
        ),
    )
    monkeypatch.setattr(source_workbench, "write_slice_upload_metadata", lambda *a, **k: None)
    monkeypatch.setattr(
        source_workbench,
        "stage_upload_queue",
        lambda _path: pytest.fail("skip mode must not insert an upload row"),
    )

    source_workbench.prepare_segment_finalize(videos, "seg_failed", {})
    updated = source_workbench.finalize_segment(videos, "seg_failed")

    assert updated["upload_status"] == "skipped"


def test_finalize_requeues_existing_failed_upload_row(tmp_path, monkeypatch):
    final = tmp_path / "clip.mp4"
    calls = []
    monkeypatch.delenv("BILIVE_SKIP_UPLOAD_QUEUE", raising=False)
    monkeypatch.setattr(source_workbench, "insert_upload_queue", lambda _path: False)
    monkeypatch.setattr(
        source_workbench,
        "get_upload_item",
        lambda _path: {"status": "failed", "remote_filename": ""},
    )
    monkeypatch.setattr(
        source_workbench,
        "requeue_failed_upload",
        lambda path: calls.append(path) or {"status": "queued"},
    )

    result = source_workbench._queue_final_output(final)

    assert result == {"status": "queued", "created": False}
    assert calls == [str(final)]


def test_finalize_metadata_failure_is_fail_closed_and_recoverable(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)

    monkeypatch.setattr(
        source_workbench,
        "slice_video",
        lambda _source, output, _start, _duration: output.write_bytes(b"raw"),
    )
    monkeypatch.setattr(
        source_workbench,
        "transcribe_segment_audio",
        lambda _path, _duration: {
            "transcript": "待发布字幕",
            "segments": [{"start": 0.0, "end": 1.0, "text": "待发布字幕"}],
        },
    )

    def fake_burn(_raw, _analysis, output, _style):
        output.write_bytes(b"final")
        return SimpleNamespace(burned=True, message="ok")

    monkeypatch.setattr(source_workbench, "burn_final_subtitles", fake_burn)
    monkeypatch.setattr(
        source_workbench,
        "write_slice_upload_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        source_workbench,
        "stage_upload_queue",
        lambda _path: pytest.fail("metadata failure must not queue the output"),
    )

    source_workbench.prepare_segment_finalize(videos, "seg_failed", {})
    with pytest.raises(source_workbench.SegmentFinalizeError) as error:
        source_workbench.finalize_segment(videos, "seg_failed")

    assert error.value.failure["stage"] == "metadata"
    failed = source_workbench._read_segment(videos, "seg_failed")[2]
    assert failed["failure"]["code"] == "metadata_write_failed"
    assert failed["artifacts"]["final_output"]["exists"] is True
    assert "media_id" not in failed["artifacts"]["final_output"]
    assert failed["candidate_media_id"] == ""
    assert failed["preview_available"] is False
    assert failed["upload_status"] == "not_queued"


def test_drop_and_range_segment_update_sidecar(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)

    ranged = source_workbench.update_segment_range(
        videos,
        "seg_failed",
        {"start_seconds": 12.5, "end_seconds": 45.0},
    )
    dropped = source_workbench.drop_segment(videos, "seg_failed", {"reason": "not useful"})

    assert ranged["start_seconds"] == 12.5
    assert ranged["end_seconds"] == 45.0
    assert dropped["judge_status"] == "drop"
    assert dropped["upload_status"] == "not_queued"
    assert dropped["quality_reason"] == "not useful"
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][1]["start_seconds"] == 12.5
    assert history["segments"][1]["judge_status"] == "drop"


def test_concurrent_segment_mutations_preserve_both_updates(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            source_workbench.update_segment_range,
            videos,
            "seg_keep",
            {"start_seconds": 11, "end_seconds": 69},
        )
        second = executor.submit(
            source_workbench.update_segment_range,
            videos,
            "seg_failed",
            {"start_seconds": 41, "end_seconds": 99},
        )
        first.result()
        second.result()

    history = json.loads(
        source.with_suffix(".mp4.task.json").read_text(encoding="utf-8")
    )
    by_id = {item["segment_id"]: item for item in history["segments"]}
    assert by_id["seg_keep"]["start_seconds"] == 11.0
    assert by_id["seg_failed"]["start_seconds"] == 41.0
    assert by_id["seg_keep"]["revision"] == 1
    assert by_id["seg_failed"]["revision"] == 1


def test_drop_cancels_queued_upload_but_rejects_active_upload(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    deleted = []
    metadata_deleted = []
    statuses = iter(({"status": "queued"}, {"status": "uploading"}))
    monkeypatch.setattr(
        source_workbench,
        "get_upload_item",
        lambda _path: next(statuses),
    )
    monkeypatch.setattr(
        source_workbench,
        "delete_upload_queue",
        lambda path: deleted.append(path) or True,
    )
    monkeypatch.setattr(
        source_workbench,
        "delete_slice_upload_metadata",
        lambda path: metadata_deleted.append(str(path)),
    )

    dropped = source_workbench.drop_segment(videos, "seg_keep", {"reason": "bad"})

    assert dropped["judge_status"] == "drop"
    assert deleted == [
        str(videos / "22384516" / "10s_22384516_20260602-12-56-49.mp4")
    ]
    assert metadata_deleted == deleted

    before = source.with_suffix(".mp4.task.json").read_bytes()
    with pytest.raises(source_workbench.SegmentStateConflict):
        source_workbench.drop_segment(videos, "seg_failed", {"reason": "late"})
    assert source.with_suffix(".mp4.task.json").read_bytes() == before


def test_drop_fails_closed_when_recorded_upload_state_cannot_be_read(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    history_path = source.with_suffix(".mp4.task.json")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["segments"][0]["upload_status"] = "queued"
    history_path.write_text(
        json.dumps(history, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        source_workbench,
        "get_upload_item",
        lambda _path: (_ for _ in ()).throw(OSError("database unavailable")),
    )
    before = history_path.read_bytes()

    with pytest.raises(source_workbench.SegmentStateConflict):
        source_workbench.drop_segment(videos, "seg_keep")

    assert history_path.read_bytes() == before


def test_retry_judge_segment_updates_status_from_llm_result(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)
    seen = {}

    monkeypatch.setattr(
        source_workbench,
        "extract_danmaku_text",
        lambda xml, start, end: seen.setdefault("window", (start, end)) or "danmaku",
    )
    monkeypatch.setattr(
        source_workbench,
        "analyze_candidate",
        lambda path, artist, danmaku_text="": AnalysisResult(
            title="Retried title",
            description="Retried desc",
            tags=["retry"],
            retain_recommendation=True,
            judge_status="keep",
            quality_reason="worth it",
        ),
    )

    updated = source_workbench.retry_segment_judge(videos, "seg_failed")

    assert seen["window"] == (40.0, 100.0)
    assert updated["judge_status"] == "keep"
    assert updated["title"] == "Retried title"
    assert updated["upload_status"] == "not_queued"


def test_retry_judge_preserves_review_state_when_analysis_fails(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)
    queued = []

    monkeypatch.setattr(
        source_workbench,
        "extract_danmaku_text",
        lambda *args: "danmaku",
    )
    monkeypatch.setattr(
        source_workbench,
        "analyze_candidate",
        lambda *args, **kwargs: AnalysisResult(
            title="候选片段",
            description="等待人工复核",
            tags=["直播切片"],
            retain_recommendation=False,
            quality_reason="ASR produced no transcript",
            judge_status="judge_failed",
            judge_error="ASR produced no transcript",
        ),
    )
    monkeypatch.setattr(
        source_workbench,
        "insert_upload_queue",
        lambda path: queued.append(path) or True,
    )

    updated = source_workbench.retry_segment_judge(videos, "seg_failed")

    assert updated["judge_status"] == "judge_failed"
    assert updated["judge_error"] == "ASR produced no transcript"
    assert updated["upload_status"] == "not_queued"
    assert queued == []


def test_retry_judge_uses_approved_streamer_guidance(tmp_path, monkeypatch):
    from src.dashboard.source_lifecycle import patch_streamer_profile

    videos = tmp_path / "Videos"
    _create_processed_source(videos)
    patch_streamer_profile(
        videos,
        "22384516",
        {"approved_guidance": "必须保留完整事件落点"},
    )
    seen = {}

    monkeypatch.setattr(
        source_workbench,
        "extract_danmaku_text",
        lambda *_args: "danmaku",
    )

    def fake_analyze(path, artist, danmaku_text="", **kwargs):
        seen.update(kwargs)
        return AnalysisResult(
            title="指导后的标题",
            description="说明",
            tags=["直播"],
            retain_recommendation=True,
            judge_status="keep",
            quality_reason="worth it",
        )

    monkeypatch.setattr(source_workbench, "analyze_candidate", fake_analyze)

    updated = source_workbench.retry_segment_judge(videos, "seg_failed")

    assert seen["guidance"] == "必须保留完整事件落点"
    assert updated["judge_status"] == "keep"


def test_render_segment_regenerates_candidate_path(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)
    calls = []

    def fake_slice(video_path, output_path, start_time, duration):
        calls.append((video_path, output_path, start_time, duration))
        output_path.write_bytes(b"rendered")

    monkeypatch.setattr(source_workbench, "slice_video", fake_slice)

    updated = source_workbench.render_segment(videos, "seg_failed")

    assert calls
    assert calls[0][2:] == (40.0, 60.0)
    assert updated["candidate_rel_path"] == "22384516/40s_22384516_20260602-12-56-49.mp4"
    assert (videos / updated["candidate_rel_path"]).read_bytes() == b"rendered"


def test_update_segment_subtitle_style_persists_mapping(tmp_path):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)

    updated = source_workbench.update_segment_subtitle_style(
        videos,
        "seg_keep",
        {"font_size": 26, "margin_v": 80, "alignment": 8, "outline": 2},
    )

    assert updated["subtitle_style"] == {
        "font_name": "Noto Sans SC",
        "font_size": 26,
        "margin_v": 80,
        "alignment": 8,
        "outline": 2.0,
    }
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][0]["subtitle_style"]["font_size"] == 26


def test_reburn_segment_subtitles_reslices_and_burns(tmp_path, monkeypatch):
    from src.burn import subtitle_burn
    from src.burn.subtitle_burn import BurnSubtitleResult

    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"video")
    _write_danmaku_xml(source.with_suffix(".xml"))
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    candidate = room / "10s_22384516_20260602-12-56-49.mp4"
    candidate.write_bytes(b"subtitled")
    AnalysisResult(
        title="Clip",
        description="Desc",
        transcript="hello",
    ).to_json_file(str(room / "10s_22384516_20260602-12-56-49_analysis.json"))
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg_keep",
                "source_rel_path": "22384516/22384516_20260602-12-56-49.mp4",
                "candidate_path": str(candidate),
                "candidate_rel_path": "22384516/10s_22384516_20260602-12-56-49.mp4",
                "candidate_start_seconds": 10.0,
                "candidate_end_seconds": 70.0,
                "start_seconds": 13.0,
                "end_seconds": 19.5,
                "judge_status": "keep",
                "upload_status": "queued",
                "subtitle_style": {"font_size": 28, "margin_v": 90},
            },
        ],
    )
    calls = {}

    def fake_slice(video_path, output_path, start_time, duration):
        calls["slice"] = (start_time, duration)
        output_path.write_bytes(b"raw")

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        calls["style"] = style
        calls["burn_output"] = output_path
        Path(output_path).write_bytes(b"reburned")
        return BurnSubtitleResult(burned=True, video_path=str(output_path), message="ok")

    monkeypatch.setattr(source_workbench, "slice_video", fake_slice)
    monkeypatch.setattr(subtitle_burn, "burn_subtitles_from_analysis", fake_burn)

    updated = source_workbench.reburn_segment_subtitles(videos, "seg_keep")

    assert calls["slice"] == (10.0, 60.0)
    assert calls["style"].font_size == 28
    assert calls["style"].margin_v == 90
    assert updated["subtitle_style"]["font_size"] == 28
