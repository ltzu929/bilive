import pytest

from src.dashboard.file_store import DashboardFileStore


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
