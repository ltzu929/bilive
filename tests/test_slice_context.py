from pathlib import Path

from src.autoslice import danmaku_slice
from src.autoslice.burst_detector import compute_baseline


def _write_danmaku_xml(path: Path) -> None:
    path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<i>\n"
        "  <d p=\"1.25,1,25,16777215,0,0,0,0\">hello</d>\n"
        "  <d p=\"10,1,25,16777215,0,0,0,0\">burst</d>\n"
        "  <d p=\"bad,1,25,16777215,0,0,0,0\">bad</d>\n"
        "  <d>missing p</d>\n"
        "</i>\n",
        encoding="utf-8",
    )


def test_extract_timestamps_from_xml_reads_bilibili_danmaku(tmp_path):
    xml_path = tmp_path / "source.xml"
    _write_danmaku_xml(xml_path)

    assert danmaku_slice.extract_timestamps_from_xml(str(xml_path)) == [1.25, 10.0]


def test_compute_baseline_skips_first_and_last_five_minutes_by_default():
    density = [100] * 300 + [2] * 600 + [100] * 300

    assert compute_baseline(density) == 2.0


def test_slice_video_by_danmaku_uses_xml_burst_events(tmp_path, monkeypatch):
    xml_path = tmp_path / "source.xml"
    video_path = tmp_path / "source.mp4"
    _write_danmaku_xml(xml_path)
    monkeypatch.setattr(danmaku_slice, "_get_video_duration", lambda path: 200.0)

    seen = {}

    def fake_detect_bursts(**kwargs):
        seen.update(kwargs)
        return [
            danmaku_slice.BurstEvent(
                peak_time=80.0,
                start=50.0,
                end=110.0,
                duration=60.0,
                peak_density=2.0,
                burst_ratio=4.0,
                danmaku_count=2,
            )
        ]

    monkeypatch.setattr(danmaku_slice, "detect_bursts", fake_detect_bursts)
    calls = []
    monkeypatch.setattr(
        danmaku_slice,
        "slice_video",
        lambda video, output, start, duration, progress_callback=None: calls.append(
            (video, output, start, duration, progress_callback)
        ),
    )

    slices = danmaku_slice.slice_video_by_danmaku(
        str(xml_path),
        str(video_path),
        return_metadata=True,
        burst_ratio=3.5,
        burst_window=8,
        burst_context=30,
        burst_merge_gap=6,
        burst_top_n=2,
    )

    assert seen["timestamps"] == [1.25, 10.0]
    assert seen["video_duration"] == 200.0
    assert seen["burst_ratio"] == 3.5
    assert seen["burst_window"] == 8
    assert seen["context"] == 30
    assert seen["merge_gap"] == 6
    assert seen["top_n"] == 2
    assert len(slices) == 1
    assert calls == [
        (
            str(video_path),
            str(tmp_path / "50s_source.mp4"),
            50.0,
            60.0,
            None,
        )
    ]
    assert slices[0].path == str(tmp_path / "50s_source.mp4")
    assert slices[0].density_core_start == 75.0
    assert slices[0].density_core_end == 85.0
    assert slices[0].context_start == 50.0
    assert slices[0].context_end == 110.0
    assert slices[0].duration == 60.0
    assert slices[0].danmaku_count == 2


def test_extract_danmaku_text_with_timestamps_emits_timeline(tmp_path):
    xml_path = tmp_path / "source.xml"
    _write_danmaku_xml(xml_path)

    text = danmaku_slice.extract_danmaku_text(
        str(xml_path), 0.0, 20.0, with_timestamps=True
    )

    # Chronological [mm:ss] lines, one per danmaku.
    assert text.splitlines() == ["[00:01] hello", "[00:10] burst"]


def test_extract_danmaku_text_without_timestamps_joins_plainly(tmp_path):
    xml_path = tmp_path / "source.xml"
    _write_danmaku_xml(xml_path)

    text = danmaku_slice.extract_danmaku_text(str(xml_path), 0.0, 20.0)

    assert text == "hello burst"


def test_truncate_timeline_middle_keeps_head_and_tail():
    lines = [f"[00:{i:02d}] line{i}" for i in range(20)]

    result = danmaku_slice._truncate_timeline_middle(lines, max_chars=80)

    assert len(result) <= 80 + len("\n…(中间省略)…\n")
    assert "中间省略" in result
    # First and last lines survive; the middle is dropped.
    assert result.startswith("[00:00] line0")
    assert result.rstrip().endswith("line19")
