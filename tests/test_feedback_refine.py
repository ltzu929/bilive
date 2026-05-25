import json
from pathlib import Path

from src.burn.feedback_refine import process_feedback_directory, process_feedback_file
from src.upload.slice_metadata import read_slice_upload_metadata


def _write_candidate(
    room: Path,
    name: str = "3100s_8792912_20260506-18-56-51.flv",
) -> tuple[Path, Path, Path]:
    source = room / "8792912_20260506-18-56-51.mp4"
    source.write_bytes(b"source")
    candidate = room / name
    candidate.write_bytes(b"candidate")
    edit_path = candidate.with_name(f"{candidate.stem}_edit.json")
    edit_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_video": str(source),
                "slice_video": str(candidate),
                "decision": "keep",
                "confidence": 0.8,
                "trim": {
                    "start": 0.0,
                    "end": 130.0,
                    "reason": "initial candidate",
                },
                "density_core": {"start": 3130.0, "end": 3190.0},
                "context_window": {"start": 3100.0, "end": 3230.0},
                "upload_suggestion": {
                    "title": "Good clip",
                    "description": "A good reviewed clip",
                    "tags": ["live", "highlight"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return source, candidate, edit_path


def test_process_feedback_file_refines_keep_manual_range_and_queues(
    tmp_path, monkeypatch
):
    room = tmp_path / "Videos" / "8792912"
    room.mkdir(parents=True)
    source, candidate, _ = _write_candidate(room)
    feedback_path = candidate.with_name(f"{candidate.stem}_feedback.json")
    feedback_path.write_text(
        json.dumps(
            {
                "slice_path": str(candidate),
                "source_recording": str(source),
                "room_id": "8792912",
                "decision": "keep",
                "manual_range": {
                    "start": 5.0,
                    "end": 18.0,
                    "relative_to": "slice",
                },
            }
        ),
        encoding="utf-8",
    )
    commands = []
    queued = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"refined")

    monkeypatch.setattr("src.burn.feedback_refine.subprocess.run", fake_run)
    monkeypatch.setattr(
        "src.burn.feedback_refine.insert_upload_queue",
        lambda path: queued.append(path) or True,
    )

    result = process_feedback_file(feedback_path)

    expected_clip = room / "3105s_8792912_20260506-18-56-51_refined.mp4"
    expected_edit = room / "3105s_8792912_20260506-18-56-51_refined_edit.json"
    assert result.status == "queued"
    assert result.refined_clip == str(expected_clip)
    assert result.edit_json == str(expected_edit)
    assert queued == [str(expected_clip)]
    assert commands[0][commands[0].index("-ss") + 1] == "3105"
    assert commands[0][commands[0].index("-t") + 1] == "13"

    edit_data = json.loads(expected_edit.read_text(encoding="utf-8"))
    assert edit_data["slice_video"] == str(expected_clip)
    assert edit_data["trim"] == {
        "start": 0.0,
        "end": 13.0,
        "reason": "dashboard manual_range 5.0-18.0 seconds",
    }
    assert edit_data["upload_suggestion"]["title"] == "Good clip"
    upload_metadata = read_slice_upload_metadata(expected_clip)
    assert upload_metadata["title"] == "Good clip"
    assert upload_metadata["desc"] == "A good reviewed clip"
    assert upload_metadata["tag"] == "live,highlight"
    assert upload_metadata["source"] == "https://live.bilibili.com/8792912"

    feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert feedback_data["generated_refined_clip"] == str(expected_clip)
    assert feedback_data["generated_refined_edit_json"] == str(expected_edit)
    assert feedback_data["upload_status"] == "queued"
    assert feedback_data["refined"] is True


def test_process_feedback_file_uses_context_window_when_manual_range_is_invalid(
    tmp_path, monkeypatch
):
    room = tmp_path / "Videos" / "8792912"
    room.mkdir(parents=True)
    source, candidate, _ = _write_candidate(room)
    feedback_path = candidate.with_name(f"{candidate.stem}_feedback.json")
    feedback_path.write_text(
        json.dumps(
            {
                "slice_path": str(candidate),
                "source_recording": str(source),
                "decision": "keep",
                "manual_range": {"start": 0, "end": 0, "relative_to": "slice"},
                "context_window": {"start": 3100.0, "end": 3230.0},
            }
        ),
        encoding="utf-8",
    )
    commands = []
    queued = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"refined")

    monkeypatch.setattr("src.burn.feedback_refine.subprocess.run", fake_run)
    monkeypatch.setattr(
        "src.burn.feedback_refine.insert_upload_queue",
        lambda path: queued.append(path) or True,
    )

    result = process_feedback_file(feedback_path)

    expected_clip = room / "3100s_8792912_20260506-18-56-51_refined.mp4"
    assert result.status == "queued"
    assert result.refined_clip == str(expected_clip)
    assert queued == [str(expected_clip)]
    assert commands[0][commands[0].index("-ss") + 1] == "3100"
    assert commands[0][commands[0].index("-t") + 1] == "130"


def test_process_feedback_file_uses_slice_relative_seek_when_source_is_missing(
    tmp_path, monkeypatch
):
    room = tmp_path / "Videos" / "8792912"
    room.mkdir(parents=True)
    candidate = room / "3100s_8792912_20260506-18-56-51.flv"
    candidate.write_bytes(b"candidate")
    feedback_path = candidate.with_name(f"{candidate.stem}_feedback.json")
    feedback_path.write_text(
        json.dumps(
            {
                "slice_path": str(candidate),
                "decision": "keep",
                "manual_range": {
                    "start": 5.0,
                    "end": 18.0,
                    "relative_to": "slice",
                },
            }
        ),
        encoding="utf-8",
    )
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"refined")

    monkeypatch.setattr("src.burn.feedback_refine.subprocess.run", fake_run)
    monkeypatch.setattr(
        "src.burn.feedback_refine._read_generate_metadata",
        lambda path: "Candidate title",
    )
    monkeypatch.setattr("src.burn.feedback_refine.insert_upload_queue", lambda path: True)

    result = process_feedback_file(feedback_path)

    assert result.status == "queued"
    assert commands[0][commands[0].index("-i") + 1] == str(candidate)
    assert commands[0][commands[0].index("-ss") + 1] == "5"
    assert commands[0][commands[0].index("-t") + 1] == "13"


def test_process_feedback_directory_skips_drop_and_review_without_queue(
    tmp_path, monkeypatch
):
    room = tmp_path / "Videos" / "8792912"
    room.mkdir(parents=True)
    _, drop_candidate, _ = _write_candidate(
        room, "1145s_8792912_20260506-18-56-51.flv"
    )
    _, review_candidate, _ = _write_candidate(
        room, "3100s_8792912_20260506-18-56-51.flv"
    )
    drop_candidate.with_name(f"{drop_candidate.stem}_feedback.json").write_text(
        json.dumps({"slice_path": str(drop_candidate), "decision": "drop"}),
        encoding="utf-8",
    )
    review_candidate.with_name(f"{review_candidate.stem}_feedback.json").write_text(
        json.dumps({"slice_path": str(review_candidate), "decision": "review"}),
        encoding="utf-8",
    )
    commands = []
    queued = []

    monkeypatch.setattr(
        "src.burn.feedback_refine.subprocess.run",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        "src.burn.feedback_refine.insert_upload_queue",
        lambda path: queued.append(path) or True,
    )

    results = process_feedback_directory(tmp_path / "Videos")

    assert [result.status for result in results] == [
        "skipped_decision",
        "skipped_decision",
    ]
    assert queued == []
    assert commands == []
