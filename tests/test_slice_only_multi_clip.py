from pathlib import Path

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion, TranscriptSegment


def _write_source(room: Path) -> Path:
    source = room / "123_20260624-10-00-00.mp4"
    source.write_bytes(b"x" * 1024 * 1024 * 25)
    source.with_suffix(".xml").write_text(
        "<?xml version=\"1.0\"?><i>"
        "<d p=\"10,1,25,16777215,0,0,0,0\">哈哈</d>"
        "<d p=\"20,1,25,16777215,0,0,0,0\">整不会了</d>"
        "</i>",
        encoding="utf-8",
    )
    return source


def _clip(title, start, end):
    return AnalysisResult(
        title=title,
        description=f"{title} desc",
        tags=["直播切片"],
        retain_recommendation=True,
        quality_reason="complete chat clip",
        judge_status="keep",
        quality_score=0.9,
        suggested_trim=TrimSuggestion(start, end, "clip"),
        transcript="有效字幕",
        transcript_segments=[TranscriptSegment(0.0, 1.0, "有效字幕")],
    )


def test_slice_only_outputs_multiple_mimo_clips(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: [
        _clip("Clip A", 10.0, 40.0),
        _clip("Clip B", 90.0, 130.0),
    ])

    burned = []

    def fake_burn(video_path, analysis, *, output_path=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned.append((Path(video_path), Path(output_path), analysis.title))
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))

    result = slice_module.slice_only(str(source), burst_context=120)

    assert result["status"] == "done"
    assert result["slice_count"] == 2
    assert len(result["segments"]) == 2
    assert [segment["title"] for segment in result["segments"]] == ["Clip A", "Clip B"]
    assert len(burned) == 2