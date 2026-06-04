from pathlib import Path

import pytest

from src.burn import scan_slice


pytestmark = pytest.mark.legacy


def test_scan_slice_once_processes_room_folders(tmp_path, monkeypatch):
    room = tmp_path / "8792912"
    room.mkdir()
    (tmp_path / "not-a-room.txt").write_text("ignored", encoding="utf-8")
    calls = []

    def fake_process_folder(folder_path):
        calls.append(Path(folder_path).name)
        return 2

    monkeypatch.setattr(scan_slice, "process_folder_slice_only", fake_process_folder)

    assert scan_slice.scan_slice_once(tmp_path) == 2
    assert calls == ["8792912"]


def test_process_folder_slice_only_skips_dashboard_marked_recordings(tmp_path, monkeypatch):
    room = tmp_path / "22966160"
    room.mkdir()
    pending_source = room / "pending.mp4"
    done_source = room / "done.mp4"
    clean_source = room / "clean.mp4"
    for source in [pending_source, done_source, clean_source]:
        source.write_bytes(b"video")
        source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    pending_source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")
    done_source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")

    calls = []

    monkeypatch.setattr(scan_slice, "MIN_VIDEO_SIZE", 0)
    monkeypatch.setattr(scan_slice, "slice_only", lambda path: calls.append(Path(path).name))

    assert scan_slice.process_folder_slice_only(room) == 1
    assert calls == ["clean.mp4"]
