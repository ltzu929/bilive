# Copyright (c) 2024 bilive.
# Pi 端扫描器 — 检测新视频文件并写 .pending 标记到 NFS 共享目录
#
# 设计原则:
# - 只做扫描和标记，不做任何处理
# - 所有文件操作都在 NFS 挂载目录上（保护 SD 卡）
# - .pending 标记文件使用原子写，避免 watcher 读到半写文件
# - 幂等：已有 .pending 或 .done 的文件自动跳过

import json
import os
import time
from pathlib import Path

from src.config.agent_config import (
    VIDEOS_DIR,
    SCAN_INTERVAL,
    MIN_VIDEO_SIZE,
)
from src.log.logger import scan_log


def write_pending_marker(video_path: Path, room_id: str = "") -> str:
    """为视频写 .pending 标记文件（原子写：先写临时文件再 rename）。

    Args:
        video_path: 视频文件的绝对路径（NFS 挂载路径）
        room_id: 房间号

    Returns:
        标记文件的绝对路径
    """
    pending_path = str(video_path) + ".pending"

    # 写入相对路径 + 元数据
    # PC 端会根据自身 VIDEOS_DIR 拼接绝对路径
    rel_path = f"{video_path.parent.name}/{video_path.name}"
    marker_data = {
        "video_rel_path": rel_path,  # 相对于 VIDEOS_DIR 的路径
        "room_id": room_id,
        "action": "slice",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # 原子写: 先写临时文件再 rename
    tmp_path = pending_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(marker_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, pending_path)
    except OSError as e:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise e

    return pending_path


def scan_folder(folder_path: Path) -> list[Path]:
    """扫描一个房间文件夹，返回满足条件的新视频路径。

    条件:
    - 不是正在录制的（无 flv 文件）
    - 不含 "-.mp4" 后缀（已处理的）
    - 不含 "_slice" （切片文件）
    - 有对应的 .xml 弹幕文件
    - 没有 .pending 或 .done 标记
    - 文件大小 >= MIN_VIDEO_SIZE MB
    """
    # 跳过正在录制的（有 flv 文件）
    if list(folder_path.glob("*.flv")):
        return []

    results = []
    for mp4_file in sorted(folder_path.glob("*.mp4")):
        # 跳过已处理和切片文件
        if mp4_file.name.endswith("-.mp4") or "_slice" in mp4_file.name:
            continue

        # 跳过已有标记的
        if mp4_file.with_suffix(".mp4.pending").exists():
            continue
        if mp4_file.with_suffix(".mp4.done").exists():
            continue

        # 检查弹幕文件
        xml_path = mp4_file.with_suffix(".xml")
        if not xml_path.exists():
            continue

        # 检查文件大小
        try:
            file_size_mb = mp4_file.stat().st_size / (1024 * 1024)
        except OSError:
            continue
        if file_size_mb < MIN_VIDEO_SIZE:
            continue

        results.append(mp4_file)

    return results


def run_scanner(interval: int = None):
    """持续扫描循环。在 Pi 上以独立进程运行。

    Args:
        interval: 扫描间隔（秒），None 使用配置值
    """
    interval = interval or SCAN_INTERVAL
    videos_dir = Path(VIDEOS_DIR)
    scan_log.info(f"Scanner started. Videos dir: {videos_dir}, Scan interval: {interval}s")

    while True:
        try:
            for room_folder in videos_dir.iterdir():
                if room_folder.is_dir() and room_folder.name.isdigit():
                    for video_path in scan_folder(room_folder):
                        scan_log.info(f"New video detected: {video_path}")
                        pending = write_pending_marker(video_path, room_folder.name)
                        scan_log.info(f"Marker written: {pending}")
        except Exception as e:
            scan_log.error(f"Scanner error: {e}")

        scan_log.info(f"Scan complete. Next scan in {interval}s.")
        time.sleep(interval)


if __name__ == "__main__":
    run_scanner()