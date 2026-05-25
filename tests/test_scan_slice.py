from pathlib import Path

from src.burn import scan_slice


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
