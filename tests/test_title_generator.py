from src.autoslice.title_generator import title_generator
from src.autoslice.mllm_sdk import multi_modal_analyzer
import src.config as config


def test_local_audio_title_generation_keeps_audio_model_loaded_for_batch(monkeypatch):
    calls = []

    def fake_multi_modal_analyze(*args, **kwargs):
        calls.append(kwargs)
        return "title"

    monkeypatch.setattr(config, "MULTI_MODAL_UNLOAD_AUDIO_MODEL", True)
    monkeypatch.setattr(multi_modal_analyzer, "multi_modal_analyze", fake_multi_modal_analyze)

    wrapped = title_generator("local-audio")(lambda video_path, artist: None)
    result = wrapped("clip.mp4", "artist", danmaku_text="danmaku")

    assert result == "title"
    assert calls[0]["unload_audio_model"] is False
