# Copyright (c) 2024 bilive.

import json
import subprocess

from src.config import TID
from src.log.logger import scan_log
from src.upload.extract_video_info import (
    generate_desc,
    generate_source,
    generate_tag,
    generate_title,
)
from src.upload.slice_metadata import read_slice_upload_metadata


def generate_video_data(video_path):
    title = generate_title(video_path)
    desc = generate_desc(video_path)
    tid = TID
    tag = generate_tag(video_path)
    source = generate_source(video_path)
    cover = ""
    dynamic = ""
    return title, desc, tid, tag, source, cover, dynamic


def generate_slice_data(video_path):
    metadata = read_slice_upload_metadata(video_path)
    if metadata:
        title = metadata.get("title") or "直播切片"
        desc = metadata.get("desc") or "精彩直播片段"
        tag = metadata.get("tag") or "直播切片"
        source = metadata.get("source") or "https://live.bilibili.com/"
        cover = metadata.get("cover") or ""
        dynamic = metadata.get("dynamic") or ""
        return title, desc, TID, tag, source, cover, dynamic

    try:
        command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            video_path,
        ]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT).decode(
            "utf-8"
        )
        parsed_output = json.loads(output)
        title = parsed_output["format"]["tags"]["generate"]
        tag = "直播切片"
        source = "https://live.bilibili.com/"
        return title, "", TID, tag, source, "", ""
    except Exception as e:
        scan_log.error(f"Error in generate_slice_data: {e}")
        return None, None, None, None, None, None, None


if __name__ == "__main__":
    pass
