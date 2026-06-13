import json
from concurrent.futures import ThreadPoolExecutor

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
    failed = source.with_suffix(".mp4.failed")
    assert failed.exists()
    assert json.loads(failed.read_text(encoding="utf-8"))["error_type"] == "ValueError"
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
        assert not source.with_suffix(".mp4.pending").exists()
        assert source.with_suffix(".mp4.processing").exists()
        assert read_task_history(source)["status"] == "processing"
        return {
            "status": "done",
            "slice_count": 2,
            "output_slices": [str(output_a), str(output_b)],
        }

    monkeypatch.setattr(slice_module, "slice_only", fake_slice_only)

    assert watcher.process_pending_videos(str(videos)) == 1
    assert not source.with_suffix(".mp4.processing").exists()
    assert source.with_suffix(".mp4.done").exists()

    history = read_task_history(source)
    assert history is not None
    assert history["status"] == "done"
    assert history["slice_count"] == 2
    assert history["output_slices"] == [
        "22384516/100s_22384516_20260527-12-55-32.mp4",
        "22384516/200s_22384516_20260527-12-55-32.mp4",
    ]


def test_watcher_recovers_stale_processing_marker(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    processing = source.with_suffix(".mp4.processing")
    processing.write_text(
        json.dumps(
            {
                "video_rel_path": source.relative_to(videos).as_posix(),
                "worker_pid": 999999,
            }
        ),
        encoding="utf-8",
    )

    recovered = watcher.recover_processing_markers(
        videos,
        pid_checker=lambda _pid: False,
    )

    assert recovered == 1
    assert not processing.exists()
    pending = source.with_suffix(".mp4.pending")
    assert pending.exists()
    assert json.loads(pending.read_text(encoding="utf-8"))["recovered_from"] == "processing"


def test_two_claimers_cannot_own_the_same_pending_marker(tmp_path):
    for attempt in range(20):
        room = tmp_path / str(attempt)
        room.mkdir()
        pending = room / "source.mp4.pending"
        pending.write_text('{"action":"slice"}', encoding="utf-8")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _index: watcher._claim_pending(pending),
                    range(2),
                )
            )

        assert sum(result is not None for result in results) == 1
        assert (room / "source.mp4.processing").is_file()


def test_watcher_processes_action_jobs_without_video_markers(monkeypatch, tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    calls = []

    monkeypatch.setattr(
        watcher,
        "process_action_jobs",
        lambda root: calls.append(root) or 1,
    )

    assert watcher.process_pending_videos(videos) == 1
    assert calls == [videos.resolve()]
