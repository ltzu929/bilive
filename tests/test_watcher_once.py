from src.server import watcher


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
