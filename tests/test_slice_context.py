from pathlib import Path

from src.autoslice import danmaku_slice


def _write_minimal_ass(path: Path) -> None:
    path.write_text(
        "[Events]\n"
        "Dialogue: 0,00:00:01.00,00:00:02.00,Default,,0,0,0,,hello\n",
        encoding="utf-8",
    )


def test_slice_video_by_danmaku_expands_density_core_to_context_window(
    tmp_path, monkeypatch
):
    ass_path = tmp_path / "source.ass"
    video_path = tmp_path / "source.mp4"
    _write_minimal_ass(ass_path)

    monkeypatch.setattr(
        danmaku_slice,
        "find_dense_periods",
        lambda log, timestamps, duration, top_n, max_overlap, step: [(3130, 269)],
    )
    calls = []
    monkeypatch.setattr(
        danmaku_slice,
        "slice_video",
        lambda video, output, start, duration: calls.append(
            (video, output, start, duration)
        ),
    )

    slices = danmaku_slice.slice_video_by_danmaku(
        str(ass_path),
        str(video_path),
        duration=60,
        top_n=1,
        max_overlap=30,
        step=1,
        pre_context=30,
        post_context=40,
        return_metadata=True,
    )

    assert len(slices) == 1
    assert calls == [
        (
            str(video_path),
            str(tmp_path / "3100s_source.mp4"),
            3100,
            130,
        )
    ]
    assert slices[0].path == str(tmp_path / "3100s_source.mp4")
    assert slices[0].density_core_start == 3130
    assert slices[0].density_core_end == 3190
    assert slices[0].context_start == 3100
    assert slices[0].context_end == 3230
    assert slices[0].duration == 130


def test_slice_video_by_danmaku_clamps_context_start_to_zero(tmp_path, monkeypatch):
    ass_path = tmp_path / "source.ass"
    video_path = tmp_path / "source.mp4"
    _write_minimal_ass(ass_path)

    monkeypatch.setattr(
        danmaku_slice,
        "find_dense_periods",
        lambda log, timestamps, duration, top_n, max_overlap, step: [(10, 42)],
    )
    calls = []
    monkeypatch.setattr(
        danmaku_slice,
        "slice_video",
        lambda video, output, start, duration: calls.append(
            (video, output, start, duration)
        ),
    )

    slices = danmaku_slice.slice_video_by_danmaku(
        str(ass_path),
        str(video_path),
        duration=60,
        top_n=1,
        max_overlap=30,
        step=1,
        pre_context=30,
        post_context=40,
        return_metadata=True,
    )

    assert calls[0][2] == 0
    assert calls[0][3] == 110
    assert slices[0].path == str(tmp_path / "0s_source.mp4")
    assert slices[0].density_core_start == 10
    assert slices[0].density_core_end == 70
    assert slices[0].context_start == 0
    assert slices[0].context_end == 110
