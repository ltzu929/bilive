from types import SimpleNamespace

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.burn import slice_only as slice_only_module
from src.burn.subtitle_burn import BurnSubtitleResult
from src.db import conn


class FakeProgressWriter:
    def update(self, **kwargs):
        return kwargs

    def error(self, message, **kwargs):
        return {"message": message, **kwargs}

    def complete(self, **kwargs):
        return kwargs


def _setup_pipeline(tmp_path, monkeypatch, analysis):
    source = tmp_path / "Videos" / "22384516" / "22384516_20260609-10-00-00.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"recording")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    candidate = source.parent / "100s_22384516_20260609-10-00-00.mp4"
    candidate.write_bytes(b"candidate")
    generated = [
        SimpleNamespace(
            path=str(candidate),
            context_start=100.0,
            context_end=220.0,
            duration=120.0,
            density_core_start=155.0,
            density_core_end=165.0,
            danmaku_count=80,
        )
    ]
    db_path = tmp_path / "upload.db"
    conn.migrate_upload_queue(db_path)

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(
        slice_only_module,
        "get_video_info",
        lambda path: ("recording", "主播", "2026-06-09"),
    )
    monkeypatch.setattr(
        slice_only_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: generated,
    )
    monkeypatch.setattr(
        slice_only_module,
        "extract_danmaku_text",
        lambda *args: "高能 弹幕反馈",
    )
    monkeypatch.setattr(
        slice_only_module,
        "analyze_candidate",
        lambda *args, **kwargs: analysis,
    )
    monkeypatch.setattr(
        slice_only_module,
        "burn_subtitles_from_analysis",
        lambda path, result: BurnSubtitleResult(
            burned=True,
            video_path=path,
            srt_path=str(candidate.with_suffix(".srt")),
            message="subtitles burned",
        ),
    )
    monkeypatch.setattr(
        slice_only_module,
        "insert_upload_queue",
        lambda path: conn.insert_upload_queue(path, db_path=db_path),
    )
    monkeypatch.setattr(
        slice_only_module,
        "get_upload_item",
        lambda path: conn.get_upload_item(path, db_path=db_path),
        raising=False,
    )
    monkeypatch.setattr(
        slice_only_module,
        "delete_upload_queue",
        lambda path: conn.delete_upload_queue(path, db_path=db_path),
        raising=False,
    )
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)
    monkeypatch.delenv("BILIVE_SKIP_UPLOAD_QUEUE", raising=False)
    return source, candidate, db_path


def test_kept_candidate_is_queued_once_and_reprocessing_is_idempotent(
    tmp_path,
    monkeypatch,
):
    analysis = AnalysisResult(
        title="字幕与弹幕共同证明的高能片段",
        description="主播发言与观众反馈形成完整事件。",
        tags=["直播", "高能"],
        retain_recommendation=True,
        judge_status="keep",
        transcript="主播完整说完了一件有价值的事情",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=3.0, text="主播完整说完了"),
            TranscriptSegment(start=3.0, end=6.0, text="一件有价值的事情"),
        ],
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)

    first = slice_only_module.slice_only(str(source))
    second = slice_only_module.slice_only(str(source))

    rows = conn.list_upload_queue(db_path)
    assert first["slice_count"] == 1
    assert second["slice_count"] == 1
    assert len(rows) == 1
    assert rows[0]["video_path"] == str(candidate)
    assert rows[0]["status"] == "queued"
    assert candidate.with_suffix(".upload.json").is_file()


def test_review_candidate_has_no_sidecar_or_queue_row(tmp_path, monkeypatch):
    analysis = AnalysisResult(
        title="候选片段",
        description="等待人工复核",
        tags=["直播切片"],
        retain_recommendation=False,
        quality_reason="ASR produced no transcript",
        judge_status="judge_failed",
        judge_error="ASR produced no transcript",
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert candidate.is_file()
    assert not candidate.with_suffix(".upload.json").exists()
    assert conn.list_upload_queue(db_path) == []


def test_dropped_candidate_is_deleted_and_never_queued(tmp_path, monkeypatch):
    analysis = AnalysisResult(
        title="不保留",
        description="内容不足",
        tags=["直播切片"],
        retain_recommendation=False,
        quality_reason="没有形成完整事件",
        judge_status="drop",
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["segments"][0]["judge_status"] == "drop"
    assert not candidate.exists()
    assert not candidate.with_suffix(".upload.json").exists()
    assert conn.list_upload_queue(db_path) == []


def test_metadata_failure_keeps_candidate_for_review_without_queue(
    tmp_path,
    monkeypatch,
):
    analysis = AnalysisResult(
        title="值得保留的候选",
        description="证据完整，但元数据落盘失败。",
        tags=["直播", "高能"],
        retain_recommendation=True,
        judge_status="keep",
        transcript="有效转录",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=2.0, text="有效转录"),
        ],
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)
    monkeypatch.setattr(
        slice_only_module,
        "write_slice_upload_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert "metadata" in result["segments"][0]["judge_error"].lower()
    assert candidate.exists()
    assert not candidate.with_suffix(".upload.json").exists()
    assert conn.list_upload_queue(db_path) == []


def test_unexpected_candidate_stage_failure_keeps_candidate_for_review(
    tmp_path,
    monkeypatch,
):
    analysis = AnalysisResult(
        title="值得保留的候选",
        description="分析成功，但后续阶段发生未预料异常。",
        tags=["直播", "高能"],
        retain_recommendation=True,
        judge_status="keep",
        transcript="有效转录",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=2.0, text="有效转录"),
        ],
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)

    monkeypatch.setattr(
        "src.autoslice.edit_instruction_builder.maybe_write_edit_outputs",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("edit output failed")),
    )

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["judge_failed_count"] == 1
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert result["segments"][0]["judge_error"] == "edit output failed"
    assert candidate.exists()
    assert not candidate.with_suffix(".upload.json").exists()
    assert conn.list_upload_queue(db_path) == []


def test_unexpected_failure_after_enqueue_rolls_back_new_queue_row(
    tmp_path,
    monkeypatch,
):
    analysis = AnalysisResult(
        title="值得保留的候选",
        description="所有自动投稿证据完整。",
        tags=["直播", "高能"],
        retain_recommendation=True,
        judge_status="keep",
        transcript="有效转录",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=2.0, text="有效转录"),
        ],
    )
    source, candidate, db_path = _setup_pipeline(tmp_path, monkeypatch, analysis)
    real_log = slice_only_module.scan_log

    class FailAfterEnqueue:
        def info(self, message):
            if "Slice ready for upload" in message:
                raise OSError("post-enqueue failure")
            return real_log.info(message)

        def __getattr__(self, name):
            return getattr(real_log, name)

    monkeypatch.setattr(slice_only_module, "scan_log", FailAfterEnqueue())

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["judge_failed_count"] == 1
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert result["segments"][0]["upload_status"] == "not_queued"
    assert candidate.exists()
    assert not candidate.with_suffix(".upload.json").exists()
    assert conn.list_upload_queue(db_path) == []
