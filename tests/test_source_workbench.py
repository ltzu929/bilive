import json

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


def _create_processed_source(videos):
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
    assert detail["segments"][1]["candidate_media_id"]


def test_source_recording_list_counts_keep_and_judge_failed(tmp_path):
    videos = tmp_path / "Videos"
    _create_processed_source(videos)

    items = source_workbench.build_source_recording_list(videos)

    assert len(items) == 1
    assert items[0]["summary_counts"]["keep"] == 1
    assert items[0]["summary_counts"]["judge_failed"] == 1
    assert items[0]["segment_count"] == 2


def test_manual_keep_segment_updates_sidecar_and_queues_upload(tmp_path, monkeypatch):
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
        "seg_failed",
        {
            "title": "Manual title",
            "description": "Manual desc",
            "tags": ["live", "clip"],
        },
    )

    assert updated["judge_status"] == "manual_keep"
    assert updated["manual_override"] is True
    assert updated["upload_status"] == "queued"
    assert queued == [updated["candidate_path"]]
    assert metadata[0][1]["title"] == "Manual title"
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][1]["judge_status"] == "manual_keep"


def test_manual_keep_segment_reports_queue_failure(tmp_path, monkeypatch):
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

    updated = source_workbench.manual_keep_segment(videos, "seg_failed")

    assert updated["judge_status"] == "manual_keep"
    assert updated["manual_override"] is True
    assert updated["upload_status"] == "queue_failed"
    assert updated["upload_error"] == "upload queue insert returned false"
    assert metadata
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][1]["upload_status"] == "queue_failed"


def test_manual_keep_segment_treats_duplicate_queue_as_idempotent(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    source = _create_processed_source(videos)
    metadata = []

    # insert_upload_queue returns False on a duplicate video_path (the unique
    # index already has this row). The re-check finds it in the queue, so the
    # segment should be reported as queued, not queue_failed.
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

    updated = source_workbench.manual_keep_segment(videos, "seg_failed")

    assert updated["judge_status"] == "manual_keep"
    assert updated["upload_status"] == "queued"
    assert "upload_error" not in updated
    assert metadata
    history = json.loads(source.with_suffix(".mp4.task.json").read_text(encoding="utf-8"))
    assert history["segments"][1]["upload_status"] == "queued"


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
