from types import SimpleNamespace

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.burn import slice_only as slice_only_module
from src.burn.subtitle_burn import BurnSubtitleResult


def retained_analysis():
    return AnalysisResult(
        title="Clip title",
        description="Description",
        tags=["直播"],
        retain_recommendation=True,
        judge_status="keep",
        transcript="第一句",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=2.0, text="第一句"),
        ],
    )


def successful_burn(path, analysis):
    return BurnSubtitleResult(
        burned=True,
        video_path=path,
        srt_path=str(path) + ".srt",
        message="subtitles burned",
    )


class FakeProgressWriter:
    def update(self, **kwargs):
        return kwargs

    def error(self, message, **kwargs):
        return {"message": message, **kwargs}

    def complete(self, **kwargs):
        return kwargs


class RecordingProgressWriter:
    def __init__(self):
        self.state = {}
        self.updates = []

    def update(self, **kwargs):
        self.state.update({k: v for k, v in kwargs.items() if k != "force"})
        self.updates.append(dict(self.state))
        return dict(self.state)

    def error(self, message, **kwargs):
        self.state.update({"status": "error", "message": message, **kwargs})
        self.updates.append(dict(self.state))
        return dict(self.state)

    def complete(self, message="切片处理完成", **kwargs):
        self.state.update({"status": "complete", "message": message, **kwargs})
        self.updates.append(dict(self.state))
        return dict(self.state)


def test_slice_only_unloads_audio_models_once_after_batch(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    slice_paths = [tmp_path / "clip1.mp4", tmp_path / "clip2.mp4"]
    for path in slice_paths:
        path.write_bytes(b"clip")

    generated = [
        SimpleNamespace(
            path=str(path),
            context_start=0.0,
            context_end=10.0,
            duration=10.0,
            density_core_start=2.0,
            density_core_end=4.0,
        )
        for path in slice_paths
    ]
    unload_calls = []

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "analyze_candidate", lambda *args, **kwargs: retained_analysis())
    monkeypatch.setattr(slice_only_module, "burn_subtitles_from_analysis", successful_burn)
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: unload_calls.append("models"))
    monkeypatch.setenv("BILIVE_KEEP_SOURCE", "1")
    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")

    slice_only_module.slice_only(str(source))

    assert unload_calls == ["models"]


def test_slice_only_keeps_source_when_no_slices_generated(tmp_path, monkeypatch):
    source = tmp_path / "22966160" / "22966160_20260525-12-00-19.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    xml_path = source.with_suffix(".xml")
    xml_path.write_text("<i></i>", encoding="utf-8")

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: [])
    monkeypatch.delenv("BILIVE_KEEP_SOURCE", raising=False)

    slice_only_module.slice_only(str(source))

    assert source.exists()
    assert xml_path.exists()


def test_slice_only_keeps_source_by_default_after_generating_slices(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    xml_path = source.with_suffix(".xml")
    xml_path.write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
        )
    ]

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "analyze_candidate", lambda *args, **kwargs: retained_analysis())
    monkeypatch.setattr(slice_only_module, "burn_subtitles_from_analysis", successful_burn)
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)
    monkeypatch.delenv("BILIVE_KEEP_SOURCE", raising=False)
    monkeypatch.delenv("BILIVE_DELETE_SOURCE_AFTER_SLICE", raising=False)
    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")

    slice_only_module.slice_only(str(source))

    assert source.exists()
    assert xml_path.exists()


def test_slice_only_can_delete_source_when_explicitly_enabled(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    xml_path = source.with_suffix(".xml")
    xml_path.write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
        )
    ]

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "analyze_candidate", lambda *args, **kwargs: retained_analysis())
    monkeypatch.setattr(slice_only_module, "burn_subtitles_from_analysis", successful_burn)
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)
    monkeypatch.setenv("BILIVE_DELETE_SOURCE_AFTER_SLICE", "1")
    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")

    slice_only_module.slice_only(str(source))

    assert not source.exists()
    assert not xml_path.exists()


def test_slice_only_writes_diagnostics_when_video_is_too_small(tmp_path, monkeypatch):
    source = tmp_path / "22966160" / "22966160_20260525-15-00-53.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    progress = RecordingProgressWriter()

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: progress)
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 1.1)
    monkeypatch.setattr(slice_only_module, "MIN_VIDEO_SIZE", 10)

    slice_only_module.slice_only(str(source))

    diagnostics = progress.state["diagnostics"]
    result = next(item for item in diagnostics if item["id"] == "result")
    assert result["status"] == "warning"
    assert result["message"] == "录像小于切片阈值，已跳过"
    assert {"label": "大小", "value": "1.1 MB"} in result["details"]
    assert {"label": "最小阈值", "value": "10.0 MB"} in result["details"]


def test_slice_only_writes_diagnostics_when_no_bursts(tmp_path, monkeypatch):
    source = tmp_path / "22966160" / "22966160_20260525-12-00-19.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    progress = RecordingProgressWriter()

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: progress)
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(
        slice_only_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: kwargs["progress_callback"](
            {
                "event": "detect_complete",
                "danmaku_count": 5328,
                "duration_seconds": 10830.1,
                "burst_ratio": 3.0,
                "burst_window": 10,
                "baseline_density": 1.0,
                "detected_segments": 0,
                "selected_bursts": 0,
                "reason": "未检测到超过阈值的弹幕突增",
            }
        ) or [],
    )
    monkeypatch.delenv("BILIVE_KEEP_SOURCE", raising=False)

    slice_only_module.slice_only(str(source))

    diagnostics = progress.state["diagnostics"]
    burst = next(item for item in diagnostics if item["id"] == "burst")
    result = next(item for item in diagnostics if item["id"] == "result")
    cleanup = next(item for item in diagnostics if item["id"] == "cleanup")
    assert burst["status"] == "warning"
    assert {"label": "阈值", "value": "3.0x"} in burst["details"]
    assert {"label": "弹幕数", "value": "5328"} in burst["details"]
    assert result["message"] == "生成 0 个切片"
    assert cleanup["message"] == "0 切片，源文件已保留"


def test_slice_only_burns_asr_subtitles_for_retained_analysis(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
        )
    ]

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(
        slice_only_module,
        "analyze_candidate",
        lambda *args, **kwargs: retained_analysis(),
    )
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)
    monkeypatch.setenv("BILIVE_KEEP_SOURCE", "1")
    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")

    calls = []

    def fake_burn_subtitles(path, analysis):
        calls.append((path, analysis))
        return BurnSubtitleResult(
            burned=True,
            video_path=path,
            srt_path=str(slice_path.with_name(f"{slice_path.stem}_asr.srt")),
            message="subtitles burned",
        )

    monkeypatch.setattr(
        slice_only_module,
        "burn_subtitles_from_analysis",
        fake_burn_subtitles,
    )

    slice_only_module.slice_only(str(source))

    assert calls
    assert calls[0][0] == str(slice_path)
    assert calls[0][1].transcript_segments[0].text == "第一句"


def test_slice_only_retains_judge_failed_candidate_without_upload(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
            danmaku_count=12,
        )
    ]

    queued = []
    burned = []

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(
        slice_only_module,
        "analyze_candidate",
        lambda *args, **kwargs: AnalysisResult(
            title="artist精彩片段",
            description="精彩直播片段",
            tags=["直播"],
            retain_recommendation=False,
            quality_reason="LLM failed: 502",
            judge_status="judge_failed",
            judge_error="LLM failed: 502",
        ),
    )
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: queued.append(path) or True)
    monkeypatch.setattr(slice_only_module, "burn_subtitles_from_analysis", lambda *args: burned.append(args))
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)

    result = slice_only_module.slice_only(str(source))

    assert result["status"] == "done"
    assert result["slice_count"] == 0
    assert result["judge_failed_count"] == 1
    assert slice_path.exists()
    assert queued == []
    assert burned == []
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert result["segments"][0]["judge_error"] == "LLM failed: 502"
    assert result["segments"][0]["candidate_path"] == str(slice_path)
    assert result["segments"][0]["danmaku_count"] == 12


def test_slice_only_keeps_review_candidate_when_subtitle_burn_fails(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
            danmaku_count=20,
        )
    ]
    queued = []

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "analyze_candidate", lambda *args, **kwargs: retained_analysis())
    monkeypatch.setattr(
        slice_only_module,
        "burn_subtitles_from_analysis",
        lambda *args: BurnSubtitleResult(
            burned=False,
            video_path=str(slice_path),
            message="ffmpeg failed",
        ),
    )
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: queued.append(path) or True)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert slice_path.exists()
    assert queued == []
    assert not slice_path.with_suffix(".upload.json").exists()
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert result["segments"][0]["upload_status"] == "not_queued"
    assert "subtitle" in result["segments"][0]["judge_error"].lower()


def test_slice_only_does_not_report_queue_failure_as_queued(tmp_path, monkeypatch):
    source = tmp_path / "8792912" / "8792912_20260524-13-06-05.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    slice_path = source.parent / "10s_8792912_20260524-13-06-05.mp4"
    slice_path.write_bytes(b"slice")
    generated = [
        SimpleNamespace(
            path=str(slice_path),
            context_start=0.0,
            context_end=60.0,
            duration=60.0,
            density_core_start=10.0,
            density_core_end=20.0,
            danmaku_count=20,
        )
    ]

    monkeypatch.setattr(slice_only_module, "SliceProgressWriter", lambda: FakeProgressWriter())
    monkeypatch.setattr(slice_only_module, "check_file_size", lambda path: 999)
    monkeypatch.setattr(slice_only_module, "get_video_info", lambda path: ("title", "artist", "date"))
    monkeypatch.setattr(slice_only_module, "extract_danmaku_text", lambda *args: "danmaku")
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "analyze_candidate", lambda *args, **kwargs: retained_analysis())
    monkeypatch.setattr(slice_only_module, "burn_subtitles_from_analysis", successful_burn)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: False)
    monkeypatch.setattr(slice_only_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_only_module, "unload_candidate_models", lambda: None)

    result = slice_only_module.slice_only(str(source))

    assert result["slice_count"] == 0
    assert result["output_slices"] == []
    assert slice_path.exists()
    assert not slice_path.with_suffix(".upload.json").exists()
    assert result["segments"][0]["judge_status"] == "judge_failed"
    assert result["segments"][0]["upload_status"] == "not_queued"
    assert "queue" in result["segments"][0]["judge_error"].lower()
