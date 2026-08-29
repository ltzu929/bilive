import pytest

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion


def _mimo_keep(trim_start=0.0, trim_end=10.0, *, title="Good clip"):
    return AnalysisResult(
        title=title,
        description="A useful livestream highlight.",
        tags=["live", "highlight"],
        retain_recommendation=True,
        quality_score=0.9,
        completeness_score=0.9,
        confidence=0.9,
        quality_reason="video, audio, and danmaku all support keeping it",
        judge_status="keep",
        suggested_trim=TrimSuggestion(
            trim_start=trim_start,
            trim_end=trim_end,
            reason="best continuous moment",
        ),
    )


def test_analyze_candidate_sends_video_danmaku_and_duration_to_mimo(monkeypatch):
    from src.autoslice import candidate_analyzer

    mimo_calls = []

    def fake_mimo(**kwargs):
        mimo_calls.append(kwargs)
        return _mimo_keep()

    monkeypatch.setattr(candidate_analyzer, "judge_candidate_with_mimo", fake_mimo)
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "speaker explains the key moment",
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "speaker explains"},
                {"start": 2.5, "end": 5.0, "text": "the key moment"},
            ],
        },
    )

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku spike",
        candidate_duration=20.0,
        candidate_start=100.0,
        candidate_end=120.0,
    )

    assert mimo_calls == [
        {
            "video_path": "clip.mp4",
            "artist": "artist",
            "danmaku_text": "danmaku spike",
            "candidate_duration": 20.0,
        }
    ]
    assert result.judge_status == "keep"
    assert result.retain_recommendation is True
    assert [segment.text for segment in result.transcript_segments] == [
        "speaker explains",
        "the key moment",
    ]


def test_analyze_candidate_drops_before_whisper(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: AnalysisResult(
            title="",
            description="",
            tags=[],
            retain_recommendation=False,
            quality_reason="not worth keeping",
            judge_status="drop",
        ),
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Whisper must not run for MiMo drop")
        ),
    )

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku",
        candidate_duration=30.0,
        candidate_start=100.0,
        candidate_end=130.0,
    )

    assert result.judge_status == "drop"
    assert result.retain_recommendation is False
    assert result.quality_reason == "not worth keeping"


def test_analyze_candidate_keeps_then_runs_whisper_on_mimo_trim(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(candidate_analyzer, "SNAP_TRIM_TO_SEGMENTS", False)
    audio_calls = []
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(trim_start=3.0, trim_end=9.5),
    )

    def fake_analyze_audio(video_path, model, **kwargs):
        audio_calls.append((video_path, model, kwargs))
        return {
            "transcript": "speaker explains the key moment",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "speaker explains"},
                {"start": 2.0, "end": 6.5, "text": "the key moment"},
            ],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku",
        candidate_duration=20.0,
        candidate_start=100.0,
        candidate_end=120.0,
    )

    assert result.judge_status == "keep"
    assert result.transcript == "speaker explains the key moment"
    assert [segment.text for segment in result.transcript_segments] == [
        "speaker explains",
        "the key moment",
    ]
    assert audio_calls == [
        (
            "clip.mp4",
            candidate_analyzer.MULTI_MODAL_WHISPER_MODEL,
            {
                "whisper_device": candidate_analyzer.WHISPER_DEVICE,
                "whisper_compute_type": candidate_analyzer.WHISPER_COMPUTE_TYPE,
                "start_seconds": 3.0,
                "duration_seconds": 6.5,
            },
        )
    ]
    assert result.source_start == 103.0
    assert result.source_end == 109.5
    assert result.candidate_start == 100.0
    assert result.candidate_end == 120.0


@pytest.mark.parametrize(
    ("trim_start", "trim_end", "error_text"),
    [
        (-1.0, 10.0, "starts before"),
        (10.0, 10.0, "empty or reversed"),
        (12.0, 14.0, "shorter than 5"),
        (5.0, 25.0, "exceeds"),
        (float("nan"), 10.0, "finite"),
    ],
)
def test_analyze_candidate_rejects_invalid_mimo_trim_before_whisper(
    monkeypatch,
    trim_start,
    trim_end,
    error_text,
):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(
            trim_start=trim_start,
            trim_end=trim_end,
        ),
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Whisper must not run for invalid MiMo trim")
        ),
    )

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku",
        candidate_duration=20.0,
        candidate_start=100.0,
        candidate_end=120.0,
    )

    assert result.judge_status == "judge_failed"
    assert result.retain_recommendation is False
    assert error_text in result.judge_error
    assert result.suggested_trim is None
    assert result.source_start == 100.0
    assert result.source_end == 120.0


def test_analyze_candidate_fails_closed_without_transcript(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(),
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {"transcript": "", "segments": []},
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "artist", "danmaku")

    assert result.judge_status == "judge_failed"
    assert result.retain_recommendation is False
    assert "transcript" in result.judge_error.lower()


def test_analyze_candidate_requires_valid_timestamped_segments(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(),
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "valid words without valid timestamps",
            "segments": [
                {"start": 2.0, "end": 1.0, "text": "invalid"},
                {"start": 0.0, "end": 1.0, "text": ""},
            ],
        },
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "artist", "danmaku")

    assert result.judge_status == "judge_failed"
    assert "timestamped" in result.judge_error.lower()


def test_analyze_candidate_rejects_keep_without_title(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(title=""),
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: {
            "transcript": "valid transcript",
            "segments": [{"start": 0.0, "end": 1.0, "text": "valid transcript"}],
        },
    )

    result = candidate_analyzer.analyze_candidate("clip.mp4", "artist", "danmaku")

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


def test_analyze_candidate_clips_runs_asr_for_each_mimo_clip(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(candidate_analyzer, "SNAP_TRIM_TO_SEGMENTS", False)

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_clips_with_mimo",
        lambda **kwargs: [
            _mimo_keep(trim_start=2.0, trim_end=12.0, title="Clip A"),
            _mimo_keep(trim_start=30.0, trim_end=55.0, title="Clip B"),
        ],
    )
    audio_calls = []

    def fake_analyze_audio(video_path, model, **kwargs):
        audio_calls.append(kwargs)
        return {
            "transcript": "有效字幕",
            "segments": [{"start": 0.0, "end": 2.0, "text": "有效字幕"}],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    results = candidate_analyzer.analyze_candidate_clips(
        "candidate.mp4",
        "主播",
        "弹幕",
        candidate_start=100.0,
        candidate_end=340.0,
        candidate_duration=240.0,
    )

    assert [item.title for item in results] == ["Clip A", "Clip B"]
    assert results[0].source_start == 102.0
    assert results[1].source_end == 155.0
    assert audio_calls == [
        {
            "whisper_device": candidate_analyzer.WHISPER_DEVICE,
            "whisper_compute_type": candidate_analyzer.WHISPER_COMPUTE_TYPE,
            "start_seconds": 2.0,
            "duration_seconds": 10.0,
        },
        {
            "whisper_device": candidate_analyzer.WHISPER_DEVICE,
            "whisper_compute_type": candidate_analyzer.WHISPER_COMPUTE_TYPE,
            "start_seconds": 30.0,
            "duration_seconds": 25.0,
        },
    ]


def test_analyze_candidate_clips_allows_long_complete_trim_for_human_review(
    monkeypatch,
):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(candidate_analyzer, "SNAP_TRIM_TO_SEGMENTS", False)
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_clips_with_mimo",
        lambda **kwargs: [_mimo_keep(trim_start=10.0, trim_end=71.0)],
    )
    audio_calls = []

    def fake_analyze_audio(video_path, model, **kwargs):
        audio_calls.append(kwargs)
        return {
            "transcript": "完整事件字幕",
            "segments": [{"start": 0.0, "end": 2.0, "text": "完整事件字幕"}],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    analyzed = candidate_analyzer.analyze_candidate_clips(
        "candidate.mp4",
        "主播",
        "弹幕",
        candidate_duration=120.0,
    )

    assert analyzed[0].judge_status == "keep"
    assert analyzed[0].retain_recommendation is True
    assert audio_calls[0]["start_seconds"] == 10.0
    assert audio_calls[0]["duration_seconds"] == 61.0


@pytest.mark.parametrize(
    ("trim_start", "trim_end", "candidate_duration", "reason_text"),
    [
        (0.0, 10.0, 240.0, "candidate boundary"),
    ],
)
def test_analyze_candidate_clips_routes_unsafe_trim_shape_to_review(
    monkeypatch,
    trim_start,
    trim_end,
    candidate_duration,
    reason_text,
):
    from src.autoslice import candidate_analyzer

    result = _mimo_keep(trim_start=trim_start, trim_end=trim_end)
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe automatic trims must not run ASR or render")
        ),
    )

    analyzed = candidate_analyzer.analyze_candidate_clip_results(
        [result],
        "candidate.mp4",
        "artist",
        candidate_duration=candidate_duration,
    )

    assert analyzed[0].judge_status == "review"
    assert analyzed[0].retain_recommendation is False
    assert reason_text in analyzed[0].judge_error


def test_snap_trim_to_segments_aligns_to_sentence_boundaries():
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TranscriptSegment

    trim = TrimSuggestion(trim_start=3.2, trim_end=9.4, reason="raw")
    segments = [
        TranscriptSegment(start=0.0, end=3.0, text="a"),
        TranscriptSegment(start=3.0, end=9.0, text="b"),
        TranscriptSegment(start=9.0, end=15.0, text="c"),
    ]

    snapped = candidate_analyzer.snap_trim_to_segments(trim, segments, tolerance=1.0)

    assert snapped.trim_start == 3.0
    assert snapped.trim_end == 9.0
    assert snapped.reason == "raw"


def test_snap_trim_to_segments_keeps_endpoint_outside_tolerance():
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TranscriptSegment

    trim = TrimSuggestion(trim_start=3.0, trim_end=20.0, reason="raw")
    segments = [TranscriptSegment(start=3.0, end=9.0, text="b")]

    # trim_end 20.0 is far from any boundary (9.0) -> stays put.
    snapped = candidate_analyzer.snap_trim_to_segments(trim, segments, tolerance=1.0)

    assert snapped.trim_start == 3.0
    assert snapped.trim_end == 20.0


def test_snap_trim_to_segments_outward_only_never_cuts_a_sentence():
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TranscriptSegment

    trim = TrimSuggestion(trim_start=3.2, trim_end=9.4, reason="raw")
    segments = [
        TranscriptSegment(start=0.0, end=3.0, text="a"),
        TranscriptSegment(start=3.0, end=9.0, text="b"),
        TranscriptSegment(start=9.0, end=15.0, text="c"),
    ]

    snapped = candidate_analyzer.snap_trim_to_segments(
        trim,
        segments,
        tolerance=1.0,
        outward_only=True,
    )

    assert snapped.trim_start == 3.0
    assert snapped.trim_end == 9.4


def test_candidate_evidence_repairs_trim_and_requires_complete_event():
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TranscriptSegment

    result = _mimo_keep(trim_start=14.0, trim_end=21.0)
    result.core_start = 18.0
    result.core_end = 20.0
    segments = [
        TranscriptSegment(start=12.0, end=15.0, text="铺垫"),
        TranscriptSegment(start=15.0, end=18.0, text="发展"),
        TranscriptSegment(start=18.0, end=20.0, text="爆点"),
        TranscriptSegment(start=20.0, end=22.0, text="收尾"),
    ]

    analyzed = candidate_analyzer.analyze_candidate_clip_results(
        [result],
        "candidate.mp4",
        "主播",
        candidate_start=100.0,
        candidate_end=130.0,
        candidate_duration=30.0,
        candidate_core_start=17.0,
        candidate_core_end=21.0,
        candidate_transcript="铺垫 发展 爆点 收尾",
        candidate_transcript_segments=segments,
        require_candidate_evidence=True,
    )

    assert analyzed[0].judge_status == "keep"
    assert analyzed[0].suggested_trim.trim_start == 12.0
    assert analyzed[0].suggested_trim.trim_end == 22.0
    assert analyzed[0].source_start == 112.0
    assert analyzed[0].source_end == 122.0
    assert [segment.text for segment in analyzed[0].transcript_segments] == [
        "铺垫",
        "发展",
        "爆点",
        "收尾",
    ]


def test_candidate_evidence_routes_missing_highlight_core_to_review():
    from src.autoslice import candidate_analyzer
    from src.autoslice.analysis_result import TranscriptSegment

    result = _mimo_keep(trim_start=10.0, trim_end=30.0)
    analyzed = candidate_analyzer.analyze_candidate_clip_results(
        [result],
        "candidate.mp4",
        "主播",
        candidate_duration=60.0,
        candidate_core_start=20.0,
        candidate_core_end=24.0,
        candidate_transcript="铺垫 爆点 收尾",
        candidate_transcript_segments=[
            TranscriptSegment(start=8.0, end=15.0, text="铺垫"),
            TranscriptSegment(start=20.0, end=24.0, text="爆点"),
            TranscriptSegment(start=24.0, end=30.0, text="收尾"),
        ],
        require_candidate_evidence=True,
    )

    assert analyzed[0].judge_status == "review"
    assert "highlight core" in analyzed[0].judge_error


def test_analyze_candidate_snap_reuses_candidate_asr(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(candidate_analyzer, "SNAP_TRIM_TO_SEGMENTS", True)
    monkeypatch.setattr(candidate_analyzer, "SNAP_TRIM_TOLERANCE", 1.0)
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: _mimo_keep(trim_start=3.3, trim_end=9.4),
    )

    audio_calls = []

    def fake_analyze_audio(video_path, model, **kwargs):
        audio_calls.append(kwargs)
        return {
            "transcript": "seg one seg two seg three",
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "seg one"},
                {"start": 3.0, "end": 9.0, "text": "seg two"},
                {"start": 9.0, "end": 15.0, "text": "seg three"},
            ],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku",
        candidate_duration=20.0,
        candidate_start=100.0,
    )

    assert result.judge_status == "keep"
    # Only one ASR pass over the trim plus six seconds of bounded padding.
    assert len(audio_calls) == 1
    assert audio_calls[0]["start_seconds"] == 0.0
    assert audio_calls[0]["duration_seconds"] == 15.4
    # trim snapped to 3.0/9.0 -> source range reflects the snapped trim.
    assert result.suggested_trim.trim_start == 3.0
    assert result.suggested_trim.trim_end == 9.0
    assert result.source_start == 103.0
    assert result.source_end == 109.0
    # transcript reused from candidate ASR, offset into the trim window.
    assert result.transcript == "seg two"


def test_quality_gate_routes_low_or_missing_scores_to_review_before_asr(monkeypatch):
    from src.autoslice import candidate_analyzer

    low = _mimo_keep(trim_start=2.0, trim_end=12.0)
    low.completeness_score = 0.79
    low.confidence = 0.0
    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_with_mimo",
        lambda **kwargs: low,
    )
    monkeypatch.setattr(
        candidate_analyzer,
        "analyze_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ASR must not run for quality-gated review")
        ),
    )

    result = candidate_analyzer.analyze_candidate(
        "clip.mp4",
        "artist",
        "danmaku",
        candidate_start=100.0,
        candidate_duration=20.0,
    )

    assert result.judge_status == "review"
    assert result.retain_recommendation is False
    assert result.source_start == 102.0
    assert result.source_end == 112.0
    assert "completeness_score=0.79" in result.judge_error
    assert "confidence=0.00" in result.judge_error
