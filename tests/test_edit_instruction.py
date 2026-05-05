import json

from src.autoslice.edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TrimInstruction,
    UploadSuggestion,
)


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
