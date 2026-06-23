from src.autoslice.analysis_result import AnalysisResult
from src.burn.pipeline_stages import (
    analyze_stage,
    enqueue_stage,
    metadata_stage,
    subtitle_stage,
)
from src.burn.subtitle_burn import BurnSubtitleResult


def _analysis():
    return AnalysisResult(
        title="title",
        description="description",
        tags=["直播"],
        retain_recommendation=True,
        judge_status="keep",
    )


def test_analyze_stage_requires_analysis_result():
    calls = []

    result = analyze_stage(
        "clip.mp4",
        artist="artist",
        danmaku_text="danmaku",
        candidate_start=100.0,
        candidate_end=120.0,
        candidate_duration=20.0,
        analyzer=lambda *args, **kwargs: calls.append((args, kwargs)) or _analysis(),
    )
    assert result.judge_status == "keep"
    assert calls == [
        (
            ("clip.mp4", "artist"),
            {
                "danmaku_text": "danmaku",
                "candidate_start": 100.0,
                "candidate_end": 120.0,
                "candidate_duration": 20.0,
            },
        )
    ]


def test_subtitle_stage_returns_structured_failure():
    result = subtitle_stage(
        "clip.mp4",
        _analysis(),
        burner=lambda *_args: BurnSubtitleResult(
            burned=False,
            video_path="clip.mp4",
            message="ffmpeg failed",
        ),
    )
    assert result["ok"] is False
    assert result["error"] == "Subtitle burn failed: ffmpeg failed"


def test_metadata_stage_converts_write_error_to_result():
    result = metadata_stage(
        "clip.mp4",
        _analysis(),
        room_id="123",
        writer=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("disk full")
        ),
    )
    assert result["ok"] is False
    assert result["error"] == "Upload metadata failed: disk full"


def test_enqueue_stage_reuses_existing_active_record():
    result = enqueue_stage(
        "clip.mp4",
        insert=lambda _path: False,
        lookup=lambda _path: {"status": "uploaded"},
    )
    assert result == {
        "ok": True,
        "status": "uploaded",
        "created": False,
        "error": "",
    }
