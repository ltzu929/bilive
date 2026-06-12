import pytest

from src.autoslice.mllm_sdk import audio_analyzer


def test_unload_asr_models_clears_cached_models(monkeypatch):
    calls = []
    audio_analyzer._whisper_model = object()
    monkeypatch.setattr(audio_analyzer, "release_gpu_memory", lambda delay=3.0: calls.append(delay))

    audio_analyzer.unload_asr_models()

    assert audio_analyzer._whisper_model is None
    assert calls == [3.0]


def test_transcribe_rejects_removed_asr_engines():
    with pytest.raises(ValueError, match="faster-whisper"):
        audio_analyzer.transcribe_audio_whisper(
            "audio.wav",
            engine="openai-whisper",
        )
