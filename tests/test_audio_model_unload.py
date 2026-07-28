import pytest
import sys
import types

from src.autoslice.mllm_sdk import audio_analyzer


def test_unload_asr_models_clears_cached_models(monkeypatch):
    calls = []
    audio_analyzer._whisper_model = object()
    audio_analyzer._whisper_batch_pipeline = object()
    monkeypatch.setattr(audio_analyzer, "release_gpu_memory", lambda delay=3.0: calls.append(delay))

    audio_analyzer.unload_asr_models()

    assert audio_analyzer._whisper_model is None
    assert audio_analyzer._whisper_batch_pipeline is None
    assert calls == [3.0]


def test_transcribe_rejects_removed_asr_engines():
    with pytest.raises(ValueError, match="faster-whisper"):
        audio_analyzer.transcribe_audio_whisper(
            "audio.wav",
            engine="openai-whisper",
        )


def test_batched_whisper_falls_back_to_sequential(monkeypatch):
    calls = []

    class Segment:
        start = 0.0
        end = 1.5
        text = "有效字幕"

    class WhisperModel:
        def __init__(self, *args, **kwargs):
            calls.append(("model", kwargs))

        def transcribe(self, *args, **kwargs):
            calls.append(("sequential", kwargs))
            return iter([Segment()]), types.SimpleNamespace(language="zh")

    class BatchedInferencePipeline:
        def __init__(self, model):
            self.model = model

        def transcribe(self, *args, **kwargs):
            calls.append(("batch", kwargs))
            raise RuntimeError("batch unavailable")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = WhisperModel
    fake_module.BatchedInferencePipeline = BatchedInferencePipeline
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    audio_analyzer._whisper_model = None
    audio_analyzer._whisper_batch_pipeline = None
    audio_analyzer._whisper_model_key = None

    result = audio_analyzer.transcribe_audio_whisper("audio.wav")

    assert result["transcript"] == "有效字幕。"
    assert calls[0][1]["cpu_threads"] == 8
    assert calls[1][0] == "batch"
    assert calls[1][1]["batch_size"] == 8
    assert calls[1][1]["vad_parameters"]["min_silence_duration_ms"] == 2000
    assert calls[2][0] == "sequential"
