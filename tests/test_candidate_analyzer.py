from src.autoslice.mllm_sdk.judge import JudgeResult


def test_analyze_candidate_sends_transcript_and_danmaku_to_judge(monkeypatch):
    from src.autoslice import candidate_analyzer

    calls = {}

    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "主播说了一段有信息量的话",
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "主播说了一段"},
                {"start": 2.5, "end": 5.0, "text": "有信息量的话"},
            ],
        },
    )

    def fake_judge(**kwargs):
        calls.update(kwargs)
        return JudgeResult(
            retain=True,
            retain_reason="内容完整且观众反应强烈",
            title="值得保留的片段",
            description="主播与观众围绕同一话题产生了有效互动。",
            tags=["直播", "高能"],
        )

    monkeypatch.setattr(candidate_analyzer, "judge_and_title", fake_judge)

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "主播",
        "哈哈哈 太真实了",
    )

    assert calls["artist"] == "主播"
    assert calls["transcript"] == "主播说了一段有信息量的话"
    assert calls["danmaku_text"] == "哈哈哈 太真实了"
    assert result.judge_status == "keep"
    assert result.retain_recommendation is True
    assert [segment.text for segment in result.transcript_segments] == [
        "主播说了一段",
        "有信息量的话",
    ]


def test_analyze_candidate_does_not_call_judge_without_transcript(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {"transcript": "", "segments": []},
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_and_title",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("LLM must not run without ASR evidence")
        ),
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "主播", "弹幕")

    assert result.judge_status == "judge_failed"
    assert result.retain_recommendation is False
    assert "transcript" in result.judge_error.lower()


def test_analyze_candidate_requires_valid_timestamped_segments(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "有文本但没有可靠时间戳",
            "segments": [
                {"start": 2.0, "end": 1.0, "text": "无效"},
                {"start": 0.0, "end": 1.0, "text": ""},
            ],
        },
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_and_title",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("LLM must not run without timestamped subtitles")
        ),
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "主播", "弹幕")

    assert result.judge_status == "judge_failed"
    assert "timestamped" in result.judge_error.lower()


def test_analyze_candidate_rejects_keep_without_title(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "有效转录",
            "segments": [{"start": 0.0, "end": 1.0, "text": "有效转录"}],
        },
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_and_title",
        lambda **kwargs: JudgeResult(
            retain=True,
            retain_reason="值得保留",
            title="",
        ),
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "主播", "弹幕")

    assert result.judge_status == "judge_failed"
    assert result.retain_recommendation is False
    assert "title" in result.judge_error.lower()


def test_unload_candidate_models_releases_configured_models(monkeypatch):
    from src.autoslice import candidate_analyzer

    calls = []
    monkeypatch.setattr(
        candidate_analyzer,
        "unload_asr_models",
        lambda: calls.append("asr"),
    )
    monkeypatch.setattr(candidate_analyzer, "MULTI_MODAL_UNLOAD_AUDIO_MODEL", True)

    candidate_analyzer.unload_candidate_models()

    assert calls == ["asr"]
