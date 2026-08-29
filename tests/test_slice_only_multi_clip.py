from pathlib import Path
import threading

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion, TranscriptSegment


def _write_source(room: Path) -> Path:
    source = room / "123_20260624-10-00-00.mp4"
    source.write_bytes(b"x" * 1024 * 1024 * 25)
    source.with_suffix(".xml").write_text(
        "<?xml version=\"1.0\"?><i>"
        "<d p=\"10,1,25,16777215,0,0,0,0\">哈哈</d>"
        "<d p=\"20,1,25,16777215,0,0,0,0\">整不会了</d>"
        "</i>",
        encoding="utf-8",
    )
    return source


def _clip(title, start, end):
    return AnalysisResult(
        title=title,
        description=f"{title} desc",
        tags=["直播切片"],
        retain_recommendation=True,
        quality_reason="complete chat clip",
        judge_status="keep",
        quality_score=0.9,
        clip_type="chat",
        completeness_score=0.9,
        confidence=0.9,
        suggested_trim=TrimSuggestion(start, end, "clip"),
        transcript="有效字幕",
        transcript_segments=[TranscriptSegment(0.0, 1.0, "有效字幕")],
    )


class CaptureLog:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def text(self):
        return "\n".join(message for _, message in self.messages)


def test_slice_only_outputs_multiple_mimo_clips(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setattr(slice_module, "scan_log", CaptureLog())
    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: [
        _clip("Clip A", 10.0, 40.0),
        _clip("Clip B", 90.0, 130.0),
    ])

    burned = []

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned.append((Path(video_path), Path(output_path), analysis.title))
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))

    result = slice_module.slice_only(str(source), burst_context=120)

    assert result["status"] == "done"
    assert result["slice_count"] == 2
    assert len(result["segments"]) == 2
    assert [segment["title"] for segment in result["segments"]] == ["Clip A", "Clip B"]
    assert len(burned) == 2


def test_slice_only_quality_review_never_renders_or_queues(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setattr(slice_module, "scan_log", CaptureLog())
    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")
    review = _clip("Needs review", 10.0, 40.0)
    review.judge_status = "review"
    review.retain_recommendation = False
    review.judge_error = "Automatic publish quality gate requires review"
    review.raw_model_response = {
        "decision": "keep",
        "quality_score": 0.9,
        "completeness_score": 0.7,
        "confidence": 0.9,
    }

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(
        slice_module,
        "extract_danmaku_text",
        lambda *args, **kwargs: "弹幕",
    )
    monkeypatch.setattr(
        slice_module,
        "analyze_candidate_clips",
        lambda *args, **kwargs: [review],
    )
    monkeypatch.setattr(
        slice_module,
        "burn_subtitles_from_analysis",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("review must not render")
        ),
    )
    monkeypatch.setattr(
        slice_module,
        "insert_upload_queue",
        lambda path: (_ for _ in ()).throw(
            AssertionError("review must not enter upload queue")
        ),
    )
    monkeypatch.setattr(
        slice_module,
        "get_video_info",
        lambda path: ("title", "主播", "date"),
    )

    result = slice_module.slice_only(str(source), burst_context=120)

    assert result["status"] == "done"
    assert result["slice_count"] == 0
    assert result["segments"][0]["judge_status"] == "review"
    assert result["segments"][0]["upload_status"] == "not_queued"
    assert result["segments"][0]["preview_available"] is False
    assert result["segments"][0]["preview_reason"] == review.judge_error
    assert result["segments"][0]["mimo_raw_response"] == review.raw_model_response
    assert result["candidate_judgments"][0]["decision"] == "review"
    assert (
        result["candidate_judgments"][0]["raw_model_response"]
        == review.raw_model_response
    )
    assert result["candidate_judgments"][0]["rejection_reasons"] == [
        review.judge_error
    ]
    assert candidate.exists()


def test_slice_only_streams_ready_mimo_results_and_returns_deterministic_order(
    monkeypatch,
    tmp_path,
):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate_a = room / "0s_123_20260624-10-00-00.mp4"
    candidate_b = room / "100s_123_20260624-10-00-00.mp4"
    candidate_a.write_bytes(b"candidate a")
    candidate_b.write_bytes(b"candidate b")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate_a), 0.0, 10.0, 0.0, 240.0, 240.0, 2),
            GeneratedSlice(str(candidate_b), 400.0, 410.0, 400.0, 640.0, 240.0, 3),
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")

    lock = threading.Lock()
    second_request_started = threading.Event()
    active_requests = 0
    max_active_requests = 0
    release_first_request = threading.Event()
    first_request_finished = threading.Event()

    def fake_judge(video_path, *args, **kwargs):
        nonlocal active_requests, max_active_requests
        with lock:
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            if active_requests >= 2:
                second_request_started.set()
        second_request_started.wait(0.2)
        if Path(video_path) == candidate_a:
            release_first_request.wait(2.0)
            first_request_finished.set()
        with lock:
            active_requests -= 1
        title = "Clip A" if Path(video_path) == candidate_a else "Clip B"
        return [_clip(title, 10.0, 40.0)]

    finalized_titles = []
    finalized_while_first_pending = []

    def fake_finalize(results, *args, **kwargs):
        if results[0].title == "Clip B":
            finalized_while_first_pending.append(not first_request_finished.is_set())
            release_first_request.set()
        finalized_titles.extend(result.title for result in results)
        return results

    burned_titles = []

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned_titles.append(analysis.title)
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "judge_candidate_clips_with_mimo", fake_judge)
    monkeypatch.setattr(slice_module, "analyze_candidate_clip_results", fake_finalize)
    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), burst_context=120, mimo_parallelism=2)

    assert result["status"] == "done"
    assert max_active_requests >= 2
    assert finalized_while_first_pending == [True]
    assert set(finalized_titles) == {"Clip A", "Clip B"}
    assert set(burned_titles) == {"Clip A", "Clip B"}
    assert [segment["title"] for segment in result["segments"]] == ["Clip A", "Clip B"]


def test_slice_only_routes_lower_scored_cross_candidate_duplicate_to_review(
    monkeypatch,
    tmp_path,
):
    from src.burn import slice_only as slice_module
    from src.autoslice import candidate_analyzer
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate_a = room / "0s_123_20260624-10-00-00.mp4"
    candidate_b = room / "100s_123_20260624-10-00-00.mp4"
    candidate_a.write_bytes(b"candidate a")
    candidate_b.write_bytes(b"candidate b")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate_a), 0.0, 10.0, 0.0, 240.0, 240.0, 2),
            GeneratedSlice(str(candidate_b), 100.0, 110.0, 100.0, 340.0, 240.0, 3),
        ],
    )
    monkeypatch.setattr(
        slice_module,
        "extract_danmaku_text",
        lambda *args, **kwargs: "弹幕",
    )

    def fake_judge(video_path, *args, **kwargs):
        if Path(video_path) == candidate_a:
            result = _clip("同一个弹幕问题的回应", 100.0, 150.0)
            score = 0.85
        else:
            result = _clip("同一个弹幕问题回应", 5.0, 55.0)
            score = 0.95
        result.core_start = 5.0
        result.core_end = 8.0
        result.topic_summary = "主播回应同一个弹幕问题"
        result.quality_score = score
        result.completeness_score = score
        result.confidence = score
        return [result]

    burned = []

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(b"rendered")
        burned.append(analysis.title)
        return type("Burn", (), {"burned": True, "message": "ok"})()

    queued = []
    monkeypatch.setattr(slice_module, "judge_candidate_clips_with_mimo", fake_judge)
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "完整回应",
            # Winner raw trim 5-55 is snapped to 4-56, changing its segment id.
            "segments": [{"start": 4.0, "end": 56.0, "text": "完整回应"}],
        },
    )
    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(
        slice_module,
        "write_slice_upload_metadata",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        slice_module,
        "insert_upload_queue",
        lambda path: queued.append(path) or True,
    )
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(
        slice_module,
        "get_video_info",
        lambda path: ("title", "主播", "date"),
    )
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), mimo_request_parallelism=2)

    assert result["slice_count"] == 1
    loser, winner = result["segments"]
    assert loser["judge_status"] == "review"
    assert loser["duplicate_of"] == winner["segment_id"]
    assert "higher-scored clip" in loser["duplicate_reason"]
    assert winner["judge_status"] == "keep"
    assert winner["start_seconds"] == 104.0
    assert winner["end_seconds"] == 156.0
    assert burned == ["同一个弹幕问题回应"]
    assert len(queued) == 1


def test_dedupe_excludes_high_composite_clip_that_fails_one_quality_gate():
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    candidate_a = GeneratedSlice("a.mp4", 0.0, 10.0, 0.0, 240.0, 240.0, 2)
    candidate_b = GeneratedSlice("b.mp4", 100.0, 110.0, 100.0, 340.0, 240.0, 3)
    failing = _clip("同一主题高综合分", 100.0, 150.0)
    failing.topic_summary = "同一主题"
    failing.quality_score = 1.0
    failing.completeness_score = 1.0
    failing.confidence = 0.79
    eligible = _clip("同一主题合格片", 5.0, 55.0)
    eligible.topic_summary = "同一主题"
    eligible.quality_score = 0.85
    eligible.completeness_score = 0.85
    eligible.confidence = 0.85

    slice_module._mark_cross_candidate_duplicates(
        [
            (1, candidate_a, {"results": [failing]}),
            (2, candidate_b, {"results": [eligible]}),
        ],
        "source.mp4",
    )

    assert failing.judge_status == "review"
    assert "confidence=0.79" in failing.judge_error
    assert eligible.judge_status == "keep"
    assert not hasattr(eligible, "duplicate_of")


def test_slice_only_parallel_mimo_does_not_run_full_asr_analyzer_in_workers(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate_a = room / "0s_123_20260624-10-00-00.mp4"
    candidate_b = room / "100s_123_20260624-10-00-00.mp4"
    candidate_a.write_bytes(b"candidate a")
    candidate_b.write_bytes(b"candidate b")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate_a), 0.0, 10.0, 0.0, 240.0, 240.0, 2),
            GeneratedSlice(str(candidate_b), 100.0, 110.0, 100.0, 340.0, 240.0, 3),
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    monkeypatch.setattr(
        slice_module,
        "analyze_candidate_clips",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("full ASR analyzer must not run in MiMo worker")
        ),
    )

    lock = threading.Lock()
    second_request_started = threading.Event()
    active_requests = 0
    max_active_requests = 0
    judge_threads = []

    def fake_judge(video_path, *args, **kwargs):
        nonlocal active_requests, max_active_requests
        judge_threads.append(threading.get_ident())
        with lock:
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            if active_requests >= 2:
                second_request_started.set()
        second_request_started.wait(0.2)
        with lock:
            active_requests -= 1
        title = "Clip A" if Path(video_path) == candidate_a else "Clip B"
        return [_clip(title, 10.0, 40.0)]

    finalize_threads = []

    def fake_finalize(results, *args, **kwargs):
        finalize_threads.append(threading.get_ident())
        return results

    burned_titles = []

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned_titles.append(analysis.title)
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "judge_candidate_clips_with_mimo", fake_judge, raising=False)
    monkeypatch.setattr(slice_module, "analyze_candidate_clip_results", fake_finalize, raising=False)
    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    main_thread = threading.get_ident()
    result = slice_module.slice_only(str(source), burst_context=120, mimo_parallelism=2)

    assert result["status"] == "done"
    assert max_active_requests >= 2
    assert all(thread_id != main_thread for thread_id in judge_threads)
    assert finalize_threads == [main_thread, main_thread]
    assert set(burned_titles) == {"Clip A", "Clip B"}
    assert [segment["title"] for segment in result["segments"]] == ["Clip A", "Clip B"]


def test_slice_only_logs_mimo_clip_decisions(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")
    captured = CaptureLog()

    monkeypatch.setattr(slice_module, "scan_log", captured)
    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: [
        _clip("Clip A", 10.0, 40.0),
        _clip("Clip B", 90.0, 130.0),
    ])

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))

    result = slice_module.slice_only(str(source), burst_context=120)
    log_text = captured.text()

    assert result["status"] == "done"
    mimo = next(item for item in result["diagnostics"] if item["id"] == "mimo")
    assert mimo["status"] == "ok"
    assert {"label": "返回片段", "value": "2"} in mimo["details"]
    assert "MiMo returned 2 chat clip(s)" in log_text
    assert "Clip 1/2 keep: title=Clip A" in log_text
    assert "Clip 2/2 keep: title=Clip B" in log_text
    assert "output=" in log_text
    assert "Slice-only summary: candidates=1, final_clips=2, judge_failed=0" in log_text


def test_slice_only_logs_summary_when_mimo_returns_no_clips(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")
    captured = CaptureLog()

    monkeypatch.setattr(slice_module, "scan_log", captured)
    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    class EmptyMimoResults(list):
        empty_reason = "missing standalone context"
        raw_response_summary = "empty_reason=missing standalone context"

    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: EmptyMimoResults())
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), burst_context=120)
    log_text = captured.text()

    assert result["status"] == "done"
    assert result["slice_count"] == 0
    assert result["candidate_judgments"][0]["decision"] == "empty"
    mimo = next(item for item in result["diagnostics"] if item["id"] == "mimo")
    assert mimo["status"] == "warning"
    assert {"label": "返回片段", "value": "0"} in mimo["details"]
    assert {"label": "Empty reason", "value": "missing standalone context"} in mimo["details"]
    assert "MiMo found no postable chat clips" in log_text
    assert "reason=missing standalone context" in log_text
    assert "Slice-only summary: candidates=1, final_clips=0, judge_failed=0" in log_text
    assert "empty_candidates=1" in log_text


def test_candidate_judgment_distinguishes_explicit_drop_from_empty(tmp_path):
    from src.autoslice.mllm_sdk.mimo_video import MimoClipResults
    from src.autoslice.danmaku_slice import GeneratedSlice
    from src.burn import slice_only as slice_module

    candidate = GeneratedSlice(
        str(tmp_path / "candidate.mp4"),
        10.0,
        20.0,
        0.0,
        60.0,
        60.0,
        3,
    )
    results = MimoClipResults(
        [],
        raw_response={
            "clips": [
                {
                    "decision": "drop",
                    "reason": "ordinary goodbye",
                }
            ]
        },
    )

    judgment = slice_module._candidate_judgment_record(
        1,
        candidate,
        results,
        results,
    )

    assert judgment["decision"] == "drop"
    assert judgment["rejection_reasons"] == ["ordinary goodbye"]


def test_slice_only_runs_mimo_before_post_judge_asr(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice import candidate_analyzer
    from src.autoslice.danmaku_slice import GeneratedSlice

    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(tmp_path))
    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 50.0, 60.0, 0.0, 120.0, 120.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")

    events = []

    def fake_judge(video_path, artist, **kwargs):
        events.append(("mimo", kwargs))
        result = _clip("完整主片段", 45.0, 60.0)
        result.core_start = 52.0
        result.core_end = 56.0
        return [result]

    monkeypatch.setattr(slice_module, "judge_candidate_clips_with_mimo", fake_judge)

    def fake_analyze_audio(video_path, model, **kwargs):
        events.append(("asr", kwargs))
        return {
            "transcript": "铺垫 发展 爆点 收尾",
            "segments": [
                {"start": 17.0, "end": 23.0, "text": "铺垫"},
                {"start": 23.0, "end": 27.0, "text": "发展"},
                {"start": 27.0, "end": 31.0, "text": "爆点"},
                {"start": 31.0, "end": 37.0, "text": "收尾"},
            ],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    def fake_burn(video_path, analysis, *, output_path=None, style=None):
        Path(output_path).write_bytes(b"rendered")
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), burst_context=60)

    assert result["status"] == "done"
    assert result["slice_count"] == 1
    assert [event[0] for event in events] == ["mimo", "asr"]
    mimo_kwargs = events[0][1]
    assert mimo_kwargs["candidate_core_start"] == 50.0
    assert mimo_kwargs["candidate_core_end"] == 60.0
    assert mimo_kwargs["single_clip"] is True
    assert events[1][1]["start_seconds"] == 25.0
    assert events[1][1]["duration_seconds"] == 55.0
    assert result["segments"][0]["start_seconds"] == 42.0
    assert result["segments"][0]["end_seconds"] == 62.0
