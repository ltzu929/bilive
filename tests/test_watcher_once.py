from src.server import watcher
from src.burn.task_history import read_task_history


def test_watcher_once_processes_pending_and_exits(monkeypatch):
    calls = []

    def fake_process_pending(videos_dir=None):
        calls.append(videos_dir)
        return 2

    monkeypatch.setattr(watcher, "process_pending_videos", fake_process_pending)

    assert watcher.main(["--once", "--videos-dir", "D:/alldata/pi/bilive/Videos"]) == 0
    assert calls == ["D:/alldata/pi/bilive/Videos"]


def test_watcher_loop_uses_interval(monkeypatch):
    calls = []

    def fake_process_pending(videos_dir=None):
        calls.append(videos_dir)
        raise KeyboardInterrupt

    monkeypatch.setattr(watcher, "process_pending_videos", fake_process_pending)

    try:
        watcher.run_watcher(interval=1, videos_dir="Videos")
    except KeyboardInterrupt:
        pass

    assert calls == ["Videos"]


def test_watcher_marks_unknown_action_failed_and_removes_pending(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    pending = source.with_suffix(".mp4.pending")
    pending.write_text(
        '{"video_rel_path":"22384516/22384516_20260527-12-55-32.mp4","action":"bad"}',
        encoding="utf-8",
    )

    assert watcher.process_pending_videos(str(videos)) == 0

    assert not pending.exists()
    history = read_task_history(source)
    assert history is not None
    assert history["status"] == "failed"
    assert "Unknown action" in history["error"]


def test_watcher_rejects_legacy_render_action(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    pending = source.with_suffix(".mp4.pending")
    pending.write_text(
        '{"video_rel_path":"22384516/22384516_20260527-12-55-32.mp4","action":"render"}',
        encoding="utf-8",
    )

    assert watcher.process_pending_videos(str(videos)) == 0

    assert not pending.exists()
    history = read_task_history(source)
    assert history is not None
    assert history["status"] == "failed"
    assert "Unknown action: render" in history["error"]


def test_watcher_marks_slice_pipeline_failed_result_failed(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module

    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    pending = source.with_suffix(".mp4.pending")
    pending.write_text(
        '{"video_rel_path":"22384516/22384516_20260527-12-55-32.mp4","action":"slice"}',
        encoding="utf-8",
    )

    def fake_slice_only(_video_path, **_options):
        return {"status": "failed", "error": "burst detector failed"}

    monkeypatch.setattr(slice_module, "slice_only", fake_slice_only)

    assert watcher.process_pending_videos(str(videos)) == 0

    assert not pending.exists()
    assert not source.with_suffix(".mp4.done").exists()
    history = read_task_history(source)
    assert history is not None
    assert history["status"] == "failed"
    assert history["error"] == "burst detector failed"


def test_watcher_writes_slice_count_to_done_history(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module

    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text(
        '{"video_rel_path":"22384516/22384516_20260527-12-55-32.mp4","action":"slice"}',
        encoding="utf-8",
    )
    output_a = room / "100s_22384516_20260527-12-55-32.mp4"
    output_b = room / "200s_22384516_20260527-12-55-32.mp4"

    def fake_slice_only(_video_path, **_options):
        return {
            "status": "done",
            "slice_count": 2,
            "output_slices": [str(output_a), str(output_b)],
        }

    monkeypatch.setattr(slice_module, "slice_only", fake_slice_only)

    assert watcher.process_pending_videos(str(videos)) == 1

    history = read_task_history(source)
    assert history is not None
    assert history["status"] == "done"
    assert history["slice_count"] == 2
    assert history["output_slices"] == [
        "22384516/100s_22384516_20260527-12-55-32.mp4",
        "22384516/200s_22384516_20260527-12-55-32.mp4",
    ]
