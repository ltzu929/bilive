# Copyright (c) 2024 bilive.
# 独立切片扫描入口：替代 scan.py，只切片不渲染

import argparse
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
    # 排除两种非录制 .flv：
    #   1. 切片输出：命名含 _slice 或以 "数字s_" 开头 (e.g. 2816s_*, 715s_*)
    #   2. 已完成录制：.flv 无配对 .mp4 但有 .jsonl（原片 mp4 已被切片流程清理）
    flv_files = [
        f for f in Path(folder_path).glob("*.flv")
        if "_slice" not in f.name
        and not (f.stem.split("_")[0].rstrip("s").isdigit() and f.stem.split("_")[0].endswith("s"))
    ]
    if flv_files:
        active_recording = False
        for flv in flv_files:
            mp4_pair = flv.with_suffix(".mp4")
            jsonl_pair = flv.with_suffix(".jsonl")
            if not mp4_pair.exists() and not jsonl_pair.exists():
                scan_log.info(f"Active recording detected: {flv.name}, skipping folder.")
                active_recording = True
                break
        if active_recording:
            return 0

    # 处理已完成的 mp4 文件（排除已处理的 "-.mp4" 和切片文件）
    mp4_files = [
        mp4_file
        for mp4_file in Path(folder_path).glob("*.mp4")
        if not mp4_file.name.endswith("-.mp4")
        and not "_slice" in mp4_file.name  # 排除切片文件
        and not mp4_file.with_suffix(".mp4.pending").exists()
        and not mp4_file.with_suffix(".mp4.done").exists()
    ]

    processed = 0
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
        processed += 1

    return processed


def scan_slice_once(videos_dir=None):
    room_folder_path = Path(videos_dir or VIDEOS_DIR)
    if not room_folder_path.is_dir():
        scan_log.warning(f"Videos dir not found: {room_folder_path}")
        return 0

    processed = 0
    for room_folder in room_folder_path.iterdir():
        if room_folder.is_dir():
            processed += process_folder_slice_only(room_folder)
    return processed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run slice-only scanning.")
    parser.add_argument("--once", action="store_true", help="scan once and exit")
    parser.add_argument("--interval", type=int, default=120, help="seconds between scans")
    args = parser.parse_args(argv)

    scan_log.info("Starting slice-only scan mode...")

    if args.once:
        processed = scan_slice_once()
        scan_log.info(f"Slice scan complete. Processed {processed} video(s).")
        return 0

    while True:
        scan_slice_once()

        scan_log.info(f"Slice scan complete. Check again in {args.interval} seconds.")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
