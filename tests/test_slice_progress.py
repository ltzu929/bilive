import json
import time
from pathlib import Path

from src.autoslice import danmaku_slice
from src.autoslice.auto_slice_video.autosv.slice import slice_video as slice_module
from src.burn.slice_progress import (
    SliceProgressWriter,
    clamp_percent,
    default_progress_path,
    load_progress_state,
    parse_ffmpeg_progress_line,
)


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

    writer.update(status="running", phase="detect", phase_label="检测", message="开始")

    data = json.loads(progress_path.read_text(encoding="utf-8"))
    assert data["status"] == "running"
    assert data["phase"] == "detect"
    assert data["phase_label"] == "检测"
    assert data["message"] == "开始"
    assert data["updated_at"]
    assert not progress_path.with_suffix(".json.tmp").exists()


def test_load_progress_state_returns_idle_when_missing(tmp_path):
    state = load_progress_state(tmp_path / "missing.json")

    assert state["status"] == "idle"
    assert state["phase"] == "idle"
    assert state["phase_label"] == "空闲"
    assert state["message"] == "暂无切片任务"
    assert state["current_slice_percent"] == 0.0


def test_progress_writer_complete_uses_chinese_default_message(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    writer = SliceProgressWriter(progress_path)

    state = writer.complete()

    assert state["status"] == "complete"
    assert state["phase_label"] == "完成"
    assert state["message"] == "切片处理完成"


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


def test_load_progress_state_translates_legacy_english_text(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "phase": "complete",
                "phase_label": "Complete",
                "message": "Slice processing complete",
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )

    state = load_progress_state(progress_path)

    assert state["phase_label"] == "完成"
    assert state["message"] == "切片处理完成"


def test_default_progress_path_uses_runtime_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    assert default_progress_path() == tmp_path / "logs" / "runtime" / "slice-progress.json"


def test_default_progress_path_prefers_runtime_dir(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path / "project"))
    monkeypatch.setenv("BILIVE_RUNTIME_DIR", str(runtime_dir))

    assert default_progress_path() == runtime_dir / "logs" / "runtime" / "slice-progress.json"


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


def _write_minimal_xml(path: Path) -> None:
    path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<i>\n"
        "  <d p=\"1,1,25,16777215,0,0,0,0\">hello</d>\n"
        "  <d p=\"10,1,25,16777215,0,0,0,0\">burst</d>\n"
        "</i>\n",
        encoding="utf-8",
    )


def test_slice_video_by_danmaku_reports_slice_callback(tmp_path, monkeypatch):
    xml_path = tmp_path / "source.xml"
    video_path = tmp_path / "source.mp4"
    _write_minimal_xml(xml_path)

    monkeypatch.setattr(danmaku_slice, "_get_video_duration", lambda path: 120.0)
    monkeypatch.setattr(
        danmaku_slice,
        "detect_bursts",
        lambda **kwargs: [
            danmaku_slice.BurstEvent(
                peak_time=10.0,
                start=0.0,
                end=30.0,
                duration=30.0,
                peak_density=1.0,
                burst_ratio=3.0,
                danmaku_count=2,
            )
        ],
    )

    def fake_slice_video(video, output, start, duration, progress_callback=None):
        progress_callback(12.5)
        progress_callback(100.0)

    monkeypatch.setattr(danmaku_slice, "slice_video", fake_slice_video)
    events = []

    danmaku_slice.slice_video_by_danmaku(
        str(xml_path),
        str(video_path),
        progress_callback=events.append,
    )

    assert events[0]["event"] == "slice_start"
    assert events[0]["current_slice"] == 1
    assert events[0]["total_slices"] == 1
    assert events[1]["event"] == "slice_progress"
    assert events[1]["percent"] == 12.5
    assert events[-1]["event"] == "slice_complete"
    assert events[-1]["percent"] == 100.0
