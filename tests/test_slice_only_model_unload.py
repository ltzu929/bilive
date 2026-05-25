from types import SimpleNamespace

from src.autoslice.mllm_sdk import audio_analyzer
from src.burn import slice_only as slice_only_module
import src.config as config


class FakeProgressWriter:
    def update(self, **kwargs):
        return kwargs

    def error(self, message, **kwargs):
        return {"message": message, **kwargs}

    def complete(self, **kwargs):
        return kwargs


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
