from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment


def test_format_timed_transcript_for_prompt_includes_timestamps():
    from src.autoslice.mllm_sdk.audio_analyzer import (
        format_timed_transcript_for_prompt,
    )

    segments = [
        TranscriptSegment(start=0.0, end=2.0, text="开场白"),
        TranscriptSegment(start=75.5, end=80.0, text="爆点来了"),
    ]
    text = format_timed_transcript_for_prompt(segments, max_chars=4000)

    assert "[00:00] 开场白" in text
    assert "[01:15] 爆点来了" in text


def test_format_timed_transcript_for_prompt_accepts_dict_segments():
    from src.autoslice.mllm_sdk.audio_analyzer import (
        format_timed_transcript_for_prompt,
    )

    text = format_timed_transcript_for_prompt(
        [{"start": 61.0, "end": 63.0, "text": "第二分钟"}]
    )
    assert text == "[01:01] 第二分钟"


def test_mimo_prompt_includes_candidate_transcript():
    from src.autoslice.mllm_sdk.mimo_video import _build_prompt

    prompt = _build_prompt(
        artist="主播",
        danmaku_text="666",
        candidate_duration=120.0,
        candidate_transcript="[00:01] 你们看这个",
    )

    assert "候选 ASR 转写" in prompt
    assert "[00:01] 你们看这个" in prompt


def test_judge_candidate_clips_passes_transcript_to_prompt(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video

    calls = {}

    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.update(kwargs)
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"decision":"drop","reason":"not enough","title":"t",'
                        '"description":"d","tags":["live"],"quality_score":0.2,'
                        '"trim_start":null,"trim_end":null}'
                    )
                },
            )()
            return type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": message})()]},
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    mimo_video.judge_candidate_clips_with_mimo(
        video_path="clip.mp4",
        artist="artist",
        danmaku_text="danmaku",
        candidate_duration=12.0,
        candidate_transcript="[00:03] 专有名词测试",
        client_factory=lambda **kwargs: client,
        encoder=lambda path, max_base64_bytes: type(
            "Encoded",
            (),
            {"url": "data:video/mp4;base64,AAAA", "base64_bytes": 4},
        )(),
    )

    text = calls["messages"][1]["content"][1]["text"]
    assert "候选 ASR 转写" in text
    assert "[00:03] 专有名词测试" in text


def test_analyze_candidate_clip_results_reuses_pre_judge_segments_for_review(
    monkeypatch,
):
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TrimSuggestion

    monkeypatch.setattr(
        candidate_analyzer,
        "_run_post_judge_asr",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must reuse pre-judge ASR segments")
        ),
    )

    result = AnalysisResult(
        title="t",
        description="d",
        tags=["live"],
        retain_recommendation=False,
        judge_status="review",
        quality_score=0.9,
        suggested_trim=TrimSuggestion(trim_start=1.0, trim_end=8.0, reason="r"),
    )
    segments = [
        TranscriptSegment(start=0.0, end=2.0, text="你好"),
        TranscriptSegment(start=2.0, end=5.0, text="咩栗"),
    ]

    analyzed = candidate_analyzer.analyze_candidate_clip_results(
        [result],
        "candidate.mp4",
        "主播",
        candidate_duration=20.0,
        candidate_transcript="[00:00] 你好\n[00:02] 咩栗",
        candidate_transcript_segments=segments,
        post_judge_asr=True,
    )

    assert analyzed[0].transcript_segments == segments
    assert "咩栗" in analyzed[0].transcript


def test_analyze_candidate_clip_results_reuses_pre_judge_segments_for_low_score_keep(
    monkeypatch,
):
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TrimSuggestion

    monkeypatch.setattr(
        candidate_analyzer,
        "_run_post_judge_asr",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must reuse pre-judge ASR segments")
        ),
    )
    monkeypatch.setattr(candidate_analyzer, "MIN_QUALITY_SCORE", 0.8)
    monkeypatch.setattr(candidate_analyzer, "MIN_COMPLETENESS_SCORE", 0.8)
    monkeypatch.setattr(candidate_analyzer, "MIN_CONFIDENCE", 0.8)

    result = AnalysisResult(
        title="t",
        description="d",
        tags=["live"],
        retain_recommendation=True,
        judge_status="keep",
        quality_score=0.5,
        completeness_score=0.9,
        confidence=0.9,
        core_start=2.0,
        core_end=4.0,
        suggested_trim=TrimSuggestion(trim_start=1.0, trim_end=8.0, reason="r"),
    )
    segments = [TranscriptSegment(start=0.0, end=9.0, text="完整一句")]

    analyzed = candidate_analyzer.analyze_candidate_clip_results(
        [result],
        "candidate.mp4",
        "主播",
        candidate_duration=20.0,
        candidate_transcript_segments=segments,
        post_judge_asr=True,
    )

    assert analyzed[0].judge_status == "review"
    assert analyzed[0].transcript_segments == segments


def test_correct_transcript_segments_applies_text_only_fix(monkeypatch):
    from src.autoslice import transcript_correct

    class Completions:
        @staticmethod
        def create(**kwargs):
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"corrections":[{"index":0,'
                        '"text":"欢迎来到咩栗的直播间"}]}'
                    )
                },
            )()
            return type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": message})()]},
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    segments = [
        TranscriptSegment(start=1.0, end=3.0, text="欢迎来到咩里的直播间"),
        TranscriptSegment(start=3.0, end=5.0, text="今天继续聊天"),
    ]
    corrected = transcript_correct.correct_transcript_segments(
        segments,
        artist="咩栗",
        client_factory=lambda **kwargs: client,
    )

    assert corrected[0].start == 1.0
    assert corrected[0].end == 3.0
    assert corrected[0].text == "欢迎来到咩栗的直播间"
    assert corrected[1].text == "今天继续聊天"


def test_correct_transcript_segments_keeps_original_on_api_failure(monkeypatch):
    from src.autoslice import transcript_correct

    class Completions:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("boom")

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    segments = [TranscriptSegment(start=0.0, end=1.0, text="原句")]
    corrected = transcript_correct.correct_transcript_segments(
        segments,
        client_factory=lambda **kwargs: client,
    )
    assert corrected[0].text == "原句"


def test_correct_analysis_subtitles_updates_transcript(monkeypatch):
    from src.autoslice import transcript_correct

    class Completions:
        @staticmethod
        def create(**kwargs):
            message = type(
                "Message",
                (),
                {"content": '{"corrections":[{"index":0,"text":"修正后"}]}'},
            )()
            return type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": message})()]},
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    analysis = AnalysisResult(
        title="标题",
        description="d",
        tags=["live"],
        transcript="原句",
        transcript_segments=[TranscriptSegment(start=0.0, end=1.0, text="原句")],
    )
    transcript_correct.correct_analysis_subtitles(
        analysis,
        artist="主播",
        client_factory=lambda **kwargs: client,
    )
    assert analysis.transcript_segments[0].text == "修正后"
    assert analysis.transcript == "修正后"
