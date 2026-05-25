from src.autoslice.mllm_sdk import audio_analyzer, multi_modal_analyzer
from src.autoslice.mllm_sdk.judge import JudgeResult


def test_unload_asr_models_clears_cached_models(monkeypatch):
    calls = []
    audio_analyzer._whisper_model = object()
    audio_analyzer._qwen3_asr_model = object()
    monkeypatch.setattr(audio_analyzer, "release_gpu_memory", lambda delay=3.0: calls.append(delay))

    audio_analyzer.unload_asr_models()

    assert audio_analyzer._whisper_model is None
    assert audio_analyzer._qwen3_asr_model is None
    assert calls == [3.0]


def test_multi_modal_analyze_can_unload_audio_model(monkeypatch):
    calls = []
    monkeypatch.setattr(
        multi_modal_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "transcript",
            "segments": [],
            "emotion": "neutral",
        },
    )
    monkeypatch.setattr(
        multi_modal_analyzer,
        "judge_and_title",
        lambda **kwargs: JudgeResult(title="title", description="description"),
    )
    monkeypatch.setattr(audio_analyzer, "unload_asr_models", lambda: calls.append("unload"))

    result = multi_modal_analyzer.multi_modal_analyze(
        "clip.mp4",
        "artist",
        enable_visual=False,
        enable_audio=True,
        unload_audio_model=True,
    )

    assert result.title == "title"
    assert calls == ["unload"]


def test_multi_modal_analyze_keeps_emotion_model_loaded_without_unload_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(
        multi_modal_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "transcript",
            "segments": [],
            "emotion": "neutral",
        },
    )
    monkeypatch.setattr(
        multi_modal_analyzer,
        "judge_and_title",
        lambda **kwargs: JudgeResult(title="title", description="description"),
    )
    monkeypatch.setattr(audio_analyzer, "unload_emotion_model", lambda: calls.append("emotion"))

    result = multi_modal_analyzer.multi_modal_analyze(
        "clip.mp4",
        "artist",
        enable_visual=False,
        enable_audio=True,
        enable_emotion=True,
        unload_audio_model=False,
    )

    assert result.title == "title"
    assert calls == []
