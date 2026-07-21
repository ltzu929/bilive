from pathlib import Path

from src.autoslice.analysis_result import (
    AnalysisResult,
    TranscriptSegment,
    TrimSuggestion,
)
from src.burn.subtitle_burn import (
    BurnSubtitleResult,
    SubtitleStyle,
    burn_subtitles_from_analysis,
    format_srt_timestamp,
    segments_to_srt,
    transcript_to_segments,
)


def test_subtitle_style_default_is_byte_equivalent_to_legacy():
    assert SubtitleStyle().to_force_style() == "Fontsize=20,MarginV=60"


def test_subtitle_style_emits_optional_fields_only_when_set():
    style = SubtitleStyle(font_size=26, margin_v=80, alignment=8, outline=2.0)
    assert style.to_force_style() == "Fontsize=26,MarginV=80,Alignment=8,Outline=2"


def test_subtitle_style_from_mapping_ignores_blank_and_unknown():
    style = SubtitleStyle.from_mapping(
        {"font_size": "30", "margin_v": "", "outline": "1.5", "bogus": "x"}
    )
    assert style.font_size == 30
    assert style.margin_v == 60
    assert style.outline == 1.5
    assert style.to_mapping() == {"font_size": 30, "margin_v": 60, "outline": 1.5}


def test_format_srt_timestamp_uses_milliseconds():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(1.234) == "00:00:01,234"
    assert format_srt_timestamp(3661.2) == "01:01:01,200"


def test_segments_to_srt_filters_invalid_segments():
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[
            TranscriptSegment(start=-0.2, end=1.0, text="第一句"),
            TranscriptSegment(start=2.0, end=2.0, text="bad"),
            TranscriptSegment(start=3.0, end=4.2, text=""),
            TranscriptSegment(start=5.5, end=7.0, text="第二句"),
        ],
    )

    assert segments_to_srt(analysis.transcript_segments) == (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "第一句\n\n"
        "2\n"
        "00:00:05,500 --> 00:00:07,000\n"
        "第二句\n"
    )


def test_burn_subtitles_replaces_original_on_success(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=1.5, text="字幕"),
        ],
    )
    commands = []

    def fake_run(command, check, capture_output, text, encoding):
        commands.append(command)
        Path(command[-1]).write_bytes(b"subtitled")

    result = burn_subtitles_from_analysis(video_path, analysis, run=fake_run)

    assert result == BurnSubtitleResult(
        burned=True,
        video_path=str(video_path),
        srt_path=str(tmp_path / "12s_source_asr.srt"),
        message="subtitles burned",
    )
    assert video_path.read_bytes() == b"subtitled"
    assert commands[0][:4] == ["ffmpeg", "-y", "-i", str(video_path)]
    assert "subtitles=" in commands[0][5]
    assert commands[0][-1] == str(tmp_path / "12s_source_subtitled.tmp.mp4")


def test_burn_subtitles_combines_mimo_trim_and_subtitle_render(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=1.5, text="subtitle"),
        ],
        suggested_trim=TrimSuggestion(
            trim_start=2.5,
            trim_end=8.0,
            reason="selected by MiMo",
        ),
    )
    commands = []

    def fake_run(command, check, capture_output, text, encoding):
        commands.append(command)
        Path(command[-1]).write_bytes(b"trimmed-subtitled")

    result = burn_subtitles_from_analysis(video_path, analysis, run=fake_run)

    assert result.burned is True
    assert video_path.read_bytes() == b"trimmed-subtitled"
    assert commands == [
        [
            "ffmpeg",
            "-y",
            "-ss",
            "2.500",
            "-i",
            str(video_path),
            "-t",
            "5.500",
            "-vf",
            commands[0][9],
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(tmp_path / "12s_source_subtitled.tmp.mp4"),
        ]
    ]
    assert "subtitles=" in commands[0][9]


def test_burn_subtitles_keeps_original_on_ffmpeg_failure(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    temp_output = tmp_path / "12s_source_subtitled.tmp.mp4"
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[
            TranscriptSegment(start=0.0, end=1.5, text="字幕"),
        ],
    )

    def fake_run(command, check, capture_output, text, encoding):
        temp_output.write_bytes(b"partial")
        raise RuntimeError("ffmpeg failed")

    result = burn_subtitles_from_analysis(video_path, analysis, run=fake_run)

    assert result.burned is False
    assert "ffmpeg failed" in result.message
    assert video_path.read_bytes() == b"original"
    assert not temp_output.exists()


def test_burn_subtitles_skips_when_no_valid_segments(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[],
    )
    calls = []

    result = burn_subtitles_from_analysis(
        video_path,
        analysis,
        run=lambda *args, **kwargs: calls.append(args),
    )

    assert result.burned is False
    assert result.message == "no valid timestamped transcript segments"
    assert calls == []
    assert video_path.read_bytes() == b"original"


def test_burn_subtitles_skips_plain_transcript_without_timestamps_by_default(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript="alpha. beta. gamma.",
        transcript_segments=[],
    )
    calls = []

    result = burn_subtitles_from_analysis(
        video_path,
        analysis,
        run=lambda *args, **kwargs: calls.append(args),
        probe_duration=lambda path: 9.0,
    )

    assert result.burned is False
    assert result.message == "no valid timestamped transcript segments"
    assert calls == []
    assert video_path.read_bytes() == b"original"
    assert not (tmp_path / "12s_source_asr.srt").exists()


def test_burn_subtitles_can_explicitly_fall_back_to_plain_transcript(tmp_path):
    video_path = tmp_path / "12s_source.mp4"
    video_path.write_bytes(b"original")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript="alpha. beta. gamma.",
        transcript_segments=[],
    )

    def fake_run(command, check, capture_output, text, encoding):
        Path(command[-1]).write_bytes(b"subtitled")

    result = burn_subtitles_from_analysis(
        video_path,
        analysis,
        run=fake_run,
        probe_duration=lambda path: 9.0,
        allow_plain_transcript_fallback=True,
    )

    assert result.burned is True
    assert video_path.read_bytes() == b"subtitled"
    assert (tmp_path / "12s_source_asr.srt").read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "alpha.\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:06,000\n"
        "beta.\n\n"
        "3\n"
        "00:00:06,000 --> 00:00:09,000\n"
        "gamma.\n"
    )


def test_plain_transcript_fallback_uses_short_phrase_segments():
    segments = transcript_to_segments(
        "我要走了，我要走了，大家辛苦了，我们下个月的电台再见了。",
        12.0,
    )

    assert [segment.text for segment in segments] == [
        "我要走了，",
        "我要走了，",
        "大家辛苦了，",
        "我们下个月的电台再见了。",
    ]
    assert all(len(segment.text) <= 14 for segment in segments)
    assert all(segment.end - segment.start <= 3.0 for segment in segments)


def test_burn_subtitles_can_write_to_separate_output_path(tmp_path):
    from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment, TrimSuggestion
    from src.burn.subtitle_burn import burn_subtitles_from_analysis

    source = tmp_path / "candidate.mp4"
    output = tmp_path / "final_clip.mp4"
    source.write_bytes(b"candidate")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[TranscriptSegment(start=0.0, end=1.0, text="字幕")],
        suggested_trim=TrimSuggestion(2.0, 8.0, "clip"),
    )

    commands = []

    def fake_run(command, check, capture_output, text, encoding):
        commands.append(command)
        output.write_bytes(b"rendered")

    result = burn_subtitles_from_analysis(source, analysis, output_path=output, run=fake_run)

    assert result.burned is True
    assert source.read_bytes() == b"candidate"
    assert output.read_bytes() == b"rendered"
    assert commands[0][-1] == str(output)
