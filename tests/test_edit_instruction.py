import json

from src.autoslice.analysis_result import (
    AnalysisResult,
    Highlight,
    TranscriptSegment,
    TrimSuggestion,
)
from src.autoslice.edit_instruction_builder import (
    build_edit_instruction,
    infer_slice_start_seconds,
    maybe_write_edit_outputs,
    read_srt_evidence,
)
from src.autoslice.edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TimeRange,
    TrimInstruction,
    UploadSuggestion,
)
from src.autoslice.prompt_packager import build_prompt_markdown, write_prompt_package


def test_edit_instruction_round_trip_dict():
    instruction = EditInstruction(
        source_video="Videos/room/source.mp4",
        slice_video="Videos/room/12s_source.mp4",
        decision="keep",
        confidence=0.82,
        trim=TrimInstruction(start=2.5, end=58.0, reason="remove quiet opening"),
        segments=[
            EditSegment(
                start=8.0,
                end=18.5,
                type="highlight",
                score=0.9,
                reason="danmaku peak and useful transcript",
            )
        ],
        subtitle_evidence=[
            SubtitleEvidence(start=7.2, end=10.8, text="important transcript")
        ],
        density_core=TimeRange(start=3130.0, end=3190.0),
        context_window=TimeRange(start=3100.0, end=3230.0),
        danmaku_evidence=DanmakuEvidence(
            peak_time=12.0,
            density_reason="slice selected by danmaku density",
        ),
        edit_actions=["Keep 8.0-18.5 as the main highlight"],
        upload_suggestion=UploadSuggestion(
            title="Good clip",
            description="A useful clip",
            tags=["live", "highlight"],
        ),
    )

    data = instruction.to_dict()
    restored = EditInstruction.from_dict(data)

    assert restored.schema_version == "1.0"
    assert restored.decision == "keep"
    assert restored.confidence == 0.82
    assert restored.trim.start == 2.5
    assert restored.density_core.start == 3130.0
    assert restored.density_core.end == 3190.0
    assert restored.context_window.start == 3100.0
    assert restored.context_window.end == 3230.0
    assert restored.segments[0].reason == "danmaku peak and useful transcript"
    assert restored.subtitle_evidence[0].text == "important transcript"
    assert restored.upload_suggestion.tags == ["live", "highlight"]


def test_edit_instruction_to_json_file(tmp_path):
    output_path = tmp_path / "clip_edit.json"
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="12s_source.mp4",
        decision="review",
        confidence=0.5,
    )

    assert instruction.to_json_file(output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["decision"] == "review"
    assert data["slice_video"] == "12s_source.mp4"


def test_invalid_decision_falls_back_to_review():
    instruction = EditInstruction.from_dict(
        {
            "source_video": "source.mp4",
            "slice_video": "clip.mp4",
            "decision": "unknown",
            "confidence": 3.0,
        }
    )

    assert instruction.decision == "review"
    assert instruction.confidence == 1.0


def test_analysis_result_preserves_transcript_segments():
    result = AnalysisResult.from_dict(
        {
            "title": "Clip",
            "description": "Description",
            "transcript": "完整字幕文本",
            "transcript_segments": [
                {"start": 1.2, "end": 3.4, "text": "第一句"},
                {"start": 4.0, "end": 6.5, "text": "第二句"},
            ],
        }
    )

    assert result.transcript == "完整字幕文本"
    assert result.transcript_segments[0].start == 1.2
    assert result.transcript_segments[0].end == 3.4
    assert result.transcript_segments[0].text == "第一句"
    assert result.to_dict()["transcript_segments"][1]["text"] == "第二句"


def test_infer_slice_start_seconds_from_autosv_name():
    assert infer_slice_start_seconds("/Videos/room/123s_record.mp4") == 123.0
    assert infer_slice_start_seconds("/Videos/room/0s_record.mp4") == 0.0
    assert infer_slice_start_seconds("/Videos/room/record.mp4") == 0.0


def test_build_edit_instruction_from_highlights_and_trim():
    result = AnalysisResult(
        title="Clip title",
        description="Clip description",
        tags=["tag1", "tag2"],
        quality_score=0.84,
        retain_recommendation=True,
        quality_reason="good reaction",
        highlights=[
            Highlight(start=7.0, end=15.0, score=0.92, desc="best moment")
        ],
        emotion_peak_time=11.0,
        suggested_trim=TrimSuggestion(
            trim_start=2.0,
            trim_end=55.0,
            reason="remove quiet edges",
        ),
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="/Videos/room/record.mp4",
        slice_video="/Videos/room/93s_record.mp4",
        slice_duration=130.0,
        subtitle_evidence=[],
        density_core=TimeRange(start=123.0, end=183.0),
        context_window=TimeRange(start=93.0, end=223.0),
    )

    assert instruction.decision == "keep"
    assert instruction.confidence == 0.84
    assert instruction.trim.start == 2.0
    assert instruction.trim.end == 55.0
    assert instruction.segments[0].start == 7.0
    assert instruction.segments[0].end == 15.0
    assert instruction.segments[0].reason == "best moment"
    assert instruction.danmaku_evidence.peak_time == 11.0
    assert instruction.density_core.start == 123.0
    assert instruction.density_core.end == 183.0
    assert instruction.context_window.start == 93.0
    assert instruction.context_window.end == 223.0
    assert instruction.upload_suggestion.title == "Clip title"
    assert "Keep 7.0-15.0 as the main highlight" in instruction.edit_actions


def test_build_edit_instruction_warns_when_transcript_tail_is_unfinished():
    result = AnalysisResult(
        title="Needs extension",
        description="Description",
        quality_score=0.8,
        retain_recommendation=True,
        transcript_segments=[
            TranscriptSegment(start=123.0, end=129.7, text="然后我们今天这个事情")
        ],
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="source.mp4",
        slice_video="3100s_source.mp4",
        slice_duration=130.0,
        subtitle_evidence=[],
        density_core=TimeRange(start=3130.0, end=3190.0),
        context_window=TimeRange(start=3100.0, end=3230.0),
    )

    assert any("Transcript near the end appears unfinished" in action for action in instruction.edit_actions)


def test_build_edit_instruction_degrades_without_subtitles():
    result = AnalysisResult(
        title="Needs review",
        description="A transcript-like description",
        quality_score=0.52,
        retain_recommendation=True,
        quality_reason="audio only",
        emotion_peak_time=0.0,
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="source.mp4",
        slice_video="0s_source.mp4",
        slice_duration=60.0,
        subtitle_evidence=[],
    )

    assert instruction.decision == "keep"
    assert instruction.segments[0].start == 0.0
    assert instruction.segments[0].end == 12.0
    assert instruction.subtitle_evidence == []
    assert (
        "Subtitle evidence is missing; review transcript manually"
        in instruction.edit_actions
    )


def test_build_edit_instruction_uses_analysis_transcript_segments():
    result = AnalysisResult(
        title="Clip",
        description="Description",
        quality_score=0.8,
        retain_recommendation=True,
        transcript="第一句。第二句。",
        transcript_segments=[
            TranscriptSegment(start=3.0, end=5.5, text="第一句"),
            TranscriptSegment(start=8.0, end=10.0, text="第二句"),
        ],
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="source.mp4",
        slice_video="123s_source.mp4",
        slice_duration=60.0,
        subtitle_evidence=[],
    )

    assert len(instruction.subtitle_evidence) == 2
    assert instruction.subtitle_evidence[0].start == 3.0
    assert instruction.subtitle_evidence[0].end == 5.5
    assert instruction.subtitle_evidence[0].text == "第一句"
    assert "Subtitle evidence is missing" not in "\n".join(instruction.edit_actions)


def test_read_srt_evidence_limits_items(tmp_path):
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "first line\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:06,000\n"
        "second line\n\n",
        encoding="utf-8",
    )

    evidence = read_srt_evidence(srt_path, max_items=1)

    assert len(evidence) == 1
    assert evidence[0].start == 1.0
    assert evidence[0].end == 3.0
    assert evidence[0].text == "first line"


def test_read_srt_evidence_filters_source_timeline_to_slice_window(tmp_path):
    srt_path = tmp_path / "source.srt"
    srt_path.write_text(
        "1\n"
        "00:01:00,000 --> 00:01:02,000\n"
        "before slice\n\n"
        "2\n"
        "00:02:03,000 --> 00:02:05,000\n"
        "inside slice\n\n"
        "3\n"
        "00:02:20,000 --> 00:02:22,000\n"
        "also inside\n\n",
        encoding="utf-8",
    )

    evidence = read_srt_evidence(
        srt_path,
        max_items=2,
        start_offset=123.0,
        duration=60.0,
    )

    assert len(evidence) == 2
    assert evidence[0].start == 0.0
    assert evidence[0].end == 2.0
    assert evidence[0].text == "inside slice"
    assert evidence[1].start == 17.0
    assert evidence[1].end == 19.0
    assert evidence[1].text == "also inside"


def test_build_prompt_markdown_contains_instruction_json():
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="12s_source.mp4",
        decision="keep",
        confidence=0.9,
        subtitle_evidence=[
            SubtitleEvidence(start=1.0, end=3.0, text="important transcript")
        ],
    )

    prompt = build_prompt_markdown(instruction, artist="Streamer")

    assert "# Slice Editing Follow-up Prompt" in prompt
    assert "Streamer" in prompt
    assert '"decision": "keep"' in prompt
    assert "important transcript" in prompt
    assert "Return JSON only" in prompt


def test_write_prompt_package(tmp_path):
    edit_path = tmp_path / "clip_edit.json"
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="clip.mp4",
        decision="review",
        confidence=0.5,
    )
    instruction.to_json_file(edit_path)

    prompt_path = write_prompt_package(edit_path, artist="Streamer")

    assert prompt_path == str(tmp_path / "clip_prompt.md")
    assert (tmp_path / "clip_prompt.md").is_file()
    assert "clip.mp4" in (tmp_path / "clip_prompt.md").read_text(encoding="utf-8")


def test_autoslice_exports_edit_instruction_types():
    from src.autoslice import EditInstruction as ExportedEditInstruction
    from src.autoslice import TranscriptSegment as ExportedTranscriptSegment
    from src.autoslice import build_edit_instruction as exported_builder

    assert ExportedEditInstruction is EditInstruction
    assert ExportedTranscriptSegment is TranscriptSegment
    assert exported_builder is build_edit_instruction


def test_maybe_write_edit_outputs_respects_disabled_flag(tmp_path):
    result = AnalysisResult(
        title="Clip",
        description="Description",
        quality_score=0.8,
        retain_recommendation=True,
    )
    slice_path = tmp_path / "0s_source.mp4"
    slice_path.write_bytes(b"fake")

    output = maybe_write_edit_outputs(
        analysis=result,
        source_video="source.mp4",
        slice_video=str(slice_path),
        artist="Streamer",
        slice_duration=60,
        enable_edit_instruction=False,
        enable_prompt_package=True,
    )

    assert output is None
    assert not (tmp_path / "0s_source_edit.json").exists()
    assert not (tmp_path / "0s_source_prompt.md").exists()


def test_maybe_write_edit_outputs_points_to_final_output_video(tmp_path):
    result = AnalysisResult(
        title="Clip",
        description="Description",
        quality_score=0.8,
        retain_recommendation=True,
    )
    raw_slice = tmp_path / "0s_source.mp4"
    final_slice = tmp_path / "0s_source.flv"
    raw_slice.write_bytes(b"fake")

    output = maybe_write_edit_outputs(
        analysis=result,
        source_video="source.mp4",
        slice_video=str(raw_slice),
        output_video=str(final_slice),
        artist="Streamer",
        slice_duration=60,
        enable_edit_instruction=True,
    )

    assert output == str(tmp_path / "0s_source_edit.json")
    data = json.loads((tmp_path / "0s_source_edit.json").read_text(encoding="utf-8"))
    assert data["slice_video"] == str(final_slice)
