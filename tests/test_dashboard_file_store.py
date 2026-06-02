import json

import pytest

from src.dashboard.file_store import DashboardFileStore


def test_list_rooms_uses_anchor_name_from_jsonl_medal(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260527-12-55-31.jsonl").write_text(
        json.dumps({
            "cmd": "DANMU_MSG",
            "info": [[], "", "", [30, "小米星", "呜米", 22384516]],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    rooms = DashboardFileStore(videos).list_rooms()

    assert rooms[0].to_dict() == {"room_id": "22384516", "name": "呜米"}


def test_lists_generated_slices_and_derives_feedback_path(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    source = room / "8792912_20260506-18-56-51.mp4"
    source.write_bytes(b"source")
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    store = DashboardFileStore(videos)
    slices = store.list_slices(room_id="8792912")

    assert len(slices) == 1
    assert slices[0].room_id == "8792912"
    assert slices[0].name == clip.name
    assert slices[0].source_recording.endswith(source.name)
    assert slices[0].feedback_path.endswith("_feedback.json")


def test_feedback_round_trip_is_limited_to_videos_root(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    store = DashboardFileStore(videos)
    item = store.list_slices("8792912")[0]
    feedback = store.write_feedback(
        item.id,
        {
            "decision": "drop",
            "quality_reason": "不好笑",
            "manual_range": {"start": 0, "end": 130, "relative_to": "slice"},
        },
    )

    assert feedback["decision"] == "drop"
    assert store.read_feedback(item.id)["quality_reason"] == "不好笑"


def test_list_slices_skips_symlinks_outside_videos_root(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    (room / "1145s_8792912_20260506-18-56-51.mp4").symlink_to(outside)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    slices = DashboardFileStore(videos).list_slices("8792912")

    assert [item.name for item in slices] == [clip.name]


def test_rejects_unknown_slice_ids(tmp_path):
    store = DashboardFileStore(tmp_path / "Videos")

    with pytest.raises(ValueError):
        store.write_feedback("../outside", {"decision": "keep"})


def test_build_slice_item_reads_quality_fields_from_feedback(tmp_path):
    """_build_slice_item populates quality_score, burst_ratio, burst_rank from feedback."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")
    feedback = room / "3100s_8792912_20260506-18-56-51_feedback.json"
    feedback.write_text(
        json.dumps({
            "decision": "keep",
            "quality_score": 0.85,
            "burst_ratio": 4.2,
            "burst_rank": 1,
        }),
        encoding="utf-8",
    )

    store = DashboardFileStore(videos)
    items = store.list_slices(room_id="8792912")

    assert len(items) == 1
    assert items[0].quality_score == 0.85
    assert items[0].burst_ratio == 4.2
    assert items[0].burst_rank == 1


def test_build_slice_item_reads_quality_fields_from_analysis_sidecar(tmp_path):
    """_build_slice_item reads quality fields from _analysis.json when no feedback."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")
    analysis = room / "3100s_8792912_20260506-18-56-51_analysis.json"
    analysis.write_text(
        json.dumps({
            "quality_score": 0.72,
            "burst_ratio": 3.1,
            "burst_rank": 2,
        }),
        encoding="utf-8",
    )

    store = DashboardFileStore(videos)
    items = store.list_slices(room_id="8792912")

    assert len(items) == 1
    assert items[0].quality_score == 0.72
    assert items[0].burst_ratio == 3.1
    assert items[0].burst_rank == 2


def test_build_slice_item_feedback_overrides_analysis(tmp_path):
    """Feedback sidecar takes priority over analysis for quality fields."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")
    analysis = room / "3100s_8792912_20260506-18-56-51_analysis.json"
    analysis.write_text(
        json.dumps({
            "quality_score": 0.5,
            "burst_ratio": 2.0,
            "burst_rank": 3,
        }),
        encoding="utf-8",
    )
    feedback = room / "3100s_8792912_20260506-18-56-51_feedback.json"
    feedback.write_text(
        json.dumps({
            "decision": "keep",
            "quality_score": 0.9,
            "burst_ratio": 5.0,
            "burst_rank": 1,
        }),
        encoding="utf-8",
    )

    store = DashboardFileStore(videos)
    items = store.list_slices(room_id="8792912")

    assert items[0].quality_score == 0.9
    assert items[0].burst_ratio == 5.0
    assert items[0].burst_rank == 1


def test_build_slice_item_quality_fields_default_none(tmp_path):
    """Without sidecars, quality fields default to None."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    store = DashboardFileStore(videos)
    items = store.list_slices(room_id="8792912")

    assert items[0].quality_score is None
    assert items[0].burst_ratio is None
    assert items[0].burst_rank is None
