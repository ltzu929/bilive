# Copyright (c) 2024 bilive.
# 独立切片扫描入口：替代 scan.py，只切片不渲染

import os
import time
from pathlib import Path
from src.config import VIDEOS_DIR, MIN_VIDEO_SIZE
from src.burn.slice_only import slice_only
from src.log.logger import scan_log


def process_folder_slice_only(folder_path):
    """处理文件夹中的录制文件（仅切片模式）

    Args:
        folder_path: 房间文件夹路径

    流程：
    1. 检查是否有正在录制的 flv 文件（跳过）
    2. 找到已完成的 mp4 文件
    3. 检查是否有对应的 xml 弹幕文件
    4. 调用 slice_only() 处理
    """
    # 不处理正在录制的文件夹
    flv_files = list(Path(folder_path).glob("*.flv"))
    if flv_files:
        scan_log.info(f"Found recording files in {folder_path}, skipping.")
        return

    # 处理已完成的 mp4 文件（排除已处理的 "-.mp4" 和切片文件）
    mp4_files = [
        mp4_file
        for mp4_file in Path(folder_path).glob("*.mp4")
        if not mp4_file.name.endswith("-.mp4")
        and not "_slice" in mp4_file.name  # 排除切片文件
    ]

    for mp4_file in mp4_files:
        # 检查是否有对应的 xml 弹幕文件
        xml_path = str(mp4_file)[:-4] + ".xml"
        if not os.path.exists(xml_path):
            scan_log.warning(f"No danmaku file for {mp4_file}, skipping.")
            continue

        # 检查文件大小
        file_size_mb = os.path.getsize(mp4_file) / (1024 * 1024)
        if file_size_mb < MIN_VIDEO_SIZE:
            scan_log.info(f"Video too small ({file_size_mb:.1f}MB), skipping: {mp4_file}")
            continue

        scan_log.info(f"Begin slice processing: {mp4_file}")
        slice_only(mp4_file)


if __name__ == "__main__":
    room_folder_path = VIDEOS_DIR
    scan_log.info("Starting slice-only scan mode...")

    while True:
        for room_folder in Path(room_folder_path).iterdir():
            if room_folder.is_dir():
                process_folder_slice_only(room_folder)

        scan_log.info("Slice scan complete. Check again in 120 seconds.")
        time.sleep(120)