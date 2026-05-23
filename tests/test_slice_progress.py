import json
import time
from pathlib import Path

from src.autoslice import danmaku_slice
from src.burn.slice_progress import (
    SliceProgressWriter,
    clamp_percent,
    default_progress_path,
    load_progress_state,
    parse_ffmpeg_progress_line,
)
from src.autoslice.auto_slice_video.autosv.slice import slice_video as slice_module


def test_parse_ffmpeg_out_time_ms_to_percent():
    assert parse_ffmpeg_progress_line("out_time_ms=2500000", 10.0) == 25.0


def test_parse_ffmpeg_out_time_to_percent():
    assert parse_ffmpeg_progress_line("out_time=00:00:03.500000", 10.0) == 35.0


def test_clamp_percent_limits_range():
    assert clamp_percent(-10) == 0.0
    assert clamp_percent(120) == 100.0


def test_progress_writer_writes_atomic_json(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    writer = SliceProgressWriter(progress_path)

    writer.update(status="running", phase="danmaku", phase_label="弹幕转换", message="开始")

    data = json.loads(progress_path.read_text(encoding="utf-8"))
    assert data["status"] == "running"
    assert data["phase"] == "danmaku"
    assert data["phase_label"] == "弹幕转换"
    assert data["message"] == "开始"
    assert data["updated_at"]
    assert not progress_path.with_suffix(".json.tmp").exists()


def test_load_progress_state_returns_idle_when_missing(tmp_path):
    state = load_progress_state(tmp_path / "missing.json")

    assert state["status"] == "idle"
    assert state["phase"] == "idle"
    assert state["current_slice_percent"] == 0.0


def test_load_progress_state_marks_stale(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    old_updated = time.time() - 600
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "slice",
                "updated_at": old_updated,
            }
        ),
        encoding="utf-8",
    )

    state = load_progress_state(progress_path, stale_after_seconds=60)

    assert state["status"] == "running"
    assert state["stale"] is True


def test_load_progress_state_handles_invalid_json(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    progress_path.write_text("{", encoding="utf-8")

    state = load_progress_state(progress_path)

    assert state["status"] == "idle"
    assert state["phase"] == "idle"
    assert state["error"] == ""


def test_default_progress_path_uses_runtime_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))

    assert default_progress_path() == tmp_path / "logs" / "runtime" / "slice-progress.json"


def test_slice_video_reports_ffmpeg_progress(monkeypatch, tmp_path):
    updates = []

    class FakeStdout:
        def __iter__(self):
            return iter(["out_time_ms=5000000\n", "progress=end\n"])

        def read(self):
            return ""

    class FakeProcess:
        stdout = FakeStdout()
        stderr = FakeStdout()

        def wait(self):
            return 0

    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(slice_module.subprocess, "Popen", fake_popen)

    slice_module.slice_video(
        str(tmp_path / "source.mp4"),
        str(tmp_path / "clip.mp4"),
        0,
        10,
        progress_callback=updates.append,
    )

    assert updates == [50.0, 100.0]
    assert "-progress" in commands[0]
    assert "pipe:1" in commands[0]
    assert "-nostats" in commands[0]


def _write_minimal_ass(path: Path) -> None:
    path.write_text(
        "[Events]\n"
        "Dialogue: 0,00:00:01.00,00:00:02.00,Default,,0,0,0,,hello\n",
        encoding="utf-8",
    )


def test_slice_video_by_danmaku_reports_slice_callback(tmp_path, monkeypatch):
    ass_path = tmp_path / "source.ass"
    video_path = tmp_path / "source.mp4"
    _write_minimal_ass(ass_path)

    monkeypatch.setattr(
        danmaku_slice,
        "find_dense_periods",
        lambda log, timestamps, duration, top_n, max_overlap, step: [(10, 42)],
    )

    def fake_slice_video(video, output, start, duration, progress_callback=None):
        progress_callback(12.5)
        progress_callback(100.0)

    monkeypatch.setattr(danmaku_slice, "slice_video", fake_slice_video)
    events = []

    danmaku_slice.slice_video_by_danmaku(
        str(ass_path),
        str(video_path),
        duration=60,
        top_n=1,
        progress_callback=events.append,
    )

    assert events[0]["event"] == "slice_start"
    assert events[0]["current_slice"] == 1
    assert events[0]["total_slices"] == 1
    assert events[1]["event"] == "slice_progress"
    assert events[1]["percent"] == 12.5
    assert events[-1]["event"] == "slice_complete"
    assert events[-1]["percent"] == 100.0
