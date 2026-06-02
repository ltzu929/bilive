from types import SimpleNamespace

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.autoslice.mllm_sdk import audio_analyzer
from src.burn import slice_only as slice_only_module
from src.burn.subtitle_burn import BurnSubtitleResult
import src.config as config


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
    monkeypatch.setattr(slice_only_module, "generate_title", lambda *args, **kwargs: "slice title")
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(audio_analyzer, "unload_asr_models", lambda: unload_calls.append("asr"))
    monkeypatch.setattr(audio_analyzer, "unload_emotion_model", lambda: unload_calls.append("emotion"))
    monkeypatch.setattr(config, "MLLM_MODEL", "local-audio")
    monkeypatch.setattr(config, "MULTI_MODAL_UNLOAD_AUDIO_MODEL", True)
    monkeypatch.setattr(config, "MULTI_MODAL_ENABLE_EMOTION_ANALYSIS", True)
    monkeypatch.setenv("BILIVE_KEEP_SOURCE", "1")
    monkeypatch.setenv("BILIVE_SKIP_UPLOAD_QUEUE", "1")

    slice_only_module.slice_only(str(source))

    assert unload_calls == ["asr", "emotion"]


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
    monkeypatch.setattr(slice_only_module, "generate_title", lambda *args, **kwargs: "slice title")
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "unload_local_audio_models_after_batch", lambda: None)
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
    monkeypatch.setattr(slice_only_module, "generate_title", lambda *args, **kwargs: "slice title")
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "slice_video_by_danmaku", lambda *args, **kwargs: generated)
    monkeypatch.setattr(slice_only_module, "unload_local_audio_models_after_batch", lambda: None)
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
        "generate_title",
        lambda *args, **kwargs: AnalysisResult(
            title="Clip title",
            description="Description",
            tags=["直播"],
            retain_recommendation=True,
            transcript_segments=[
                TranscriptSegment(start=0.0, end=2.0, text="第一句"),
            ],
        ),
    )
    monkeypatch.setattr(slice_only_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_only_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_only_module, "unload_local_audio_models_after_batch", lambda: None)
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
