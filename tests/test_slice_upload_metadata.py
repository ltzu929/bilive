from pathlib import Path

from src.upload.generate_upload_data import generate_slice_data
from src.upload.slice_metadata import (
    is_slice_upload,
    read_slice_upload_metadata,
    write_slice_upload_metadata,
)


def test_write_and_read_slice_upload_metadata_for_mp4(tmp_path):
    video_path = tmp_path / "50s_8792912_20260524.mp4"

    sidecar = write_slice_upload_metadata(
        video_path,
        title="切片标题",
        desc="切片简介",
        tag="直播切片,高能",
        source="https://live.bilibili.com/8792912",
        dynamic="动态文案",
    )

    assert sidecar == tmp_path / "50s_8792912_20260524.upload.json"
    assert is_slice_upload(video_path) is True
    assert read_slice_upload_metadata(video_path)["title"] == "切片标题"


def test_generate_slice_data_prefers_sidecar_metadata(tmp_path, monkeypatch):
    video_path = tmp_path / "50s_8792912_20260524.mp4"
    video_path.write_bytes(b"mp4")
    monkeypatch.setattr("src.upload.generate_upload_data.TID", 138)
    write_slice_upload_metadata(
        video_path,
        title="切片标题",
        desc="切片简介",
        tag="直播切片,高能",
        source="https://live.bilibili.com/8792912",
    )

    title, desc, tid, tag, source, cover, dynamic = generate_slice_data(str(video_path))

    assert title == "切片标题"
    assert desc == "切片简介"
    assert tid == 138
    assert tag == "直播切片,高能"
    assert source == "https://live.bilibili.com/8792912"
    assert cover == ""
    assert dynamic == ""
