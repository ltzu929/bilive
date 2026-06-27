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
        completeness_score=0.8,
        confidence=0.7,
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

    def fake_burn(video_path, analysis, *, output_path=None):
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


def test_slice_only_submits_mimo_candidates_concurrently_but_finalizes_in_order(monkeypatch, tmp_path):
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

    lock = threading.Lock()
    second_request_started = threading.Event()
    active_requests = 0
    max_active_requests = 0

    def fake_analyze(video_path, *args, **kwargs):
        nonlocal active_requests, max_active_requests
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

    burned_titles = []

    def fake_burn(video_path, analysis, *, output_path=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned_titles.append(analysis.title)
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "analyze_candidate_clips", fake_analyze)
    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), burst_context=120, mimo_parallelism=2)

    assert result["status"] == "done"
    assert max_active_requests >= 2
    assert burned_titles == ["Clip A", "Clip B"]
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

    def fake_burn(video_path, analysis, *, output_path=None):
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
    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: [])
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))
    monkeypatch.setattr(slice_module, "unload_candidate_models", lambda: None)

    result = slice_module.slice_only(str(source), burst_context=120)
    log_text = captured.text()

    assert result["status"] == "failed"
    mimo = next(item for item in result["diagnostics"] if item["id"] == "mimo")
    assert mimo["status"] == "warning"
    assert {"label": "返回片段", "value": "0"} in mimo["details"]
    assert "MiMo found no postable chat clips" in log_text
    assert "Slice-only summary: candidates=1, final_clips=0, judge_failed=0" in log_text
    assert "empty_candidates=1" in log_text
