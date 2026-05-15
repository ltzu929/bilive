# Copyright (c) 2024 bilive.
# PC 端 watcher — 监控 NFS 共享目录中的 .pending 标记文件
#
# 工作流程:
# 1. 扫描 VIDEOS_DIR 下的 *.pending 文件
# 2. 读取标记中的相对路径，拼接 PC 本地绝对路径
# 3. 调用现有处理管线 (slice_only / render_video)
# 4. 成功后将 .pending 改为 .done
# 5. 失败则保留 .pending，下次重试

import json
import os
import time
from pathlib import Path

from src.config.server_config import VIDEOS_DIR
from src.log.logger import scan_log


def process_pending_videos(videos_dir: str = None) -> int:
    """扫描 .pending 文件并执行处理管线。

    Args:
        videos_dir: 视频根目录，None 使用配置值

    Returns:
        本次处理的视频数量
    """
    videos_dir = Path(videos_dir or VIDEOS_DIR)

    if not videos_dir.is_dir():
        scan_log.warning(f"Videos dir not found: {videos_dir}")
        return 0

    processed = 0
    for pending_file in sorted(videos_dir.rglob("*.mp4.pending")):
        try:
            # 读取标记元数据
            with open(pending_file, "r", encoding="utf-8") as f:
                marker = json.load(f)

            # 标记中存的是相对路径，拼接 PC 端绝对路径
            video_rel_path = marker.get("video_rel_path", "")
            action = marker.get("action", "slice")

            if video_rel_path:
                video_path = str(videos_dir / video_rel_path)
            else:
                # 降级：使用绝对路径（不推荐，但在同一台机器上可用）
                video_path = marker.get("video_path", "")

            if not video_path or not os.path.exists(video_path):
                scan_log.warning(f"Video file not found: {video_path}, removing stale marker")
                pending_file.unlink()
                continue

            scan_log.info(f"Processing {action}: {video_path}")

            # 执行处理管线
            if action == "slice":
                from src.burn.slice_only import slice_only
                slice_only(video_path)
            elif action == "render":
                from src.burn.render_video import render_video
                render_video(video_path)
            else:
                scan_log.warning(f"Unknown action: {action}, skipping")

            # 处理成功，将 .pending 改为 .done
            done_path = str(pending_file).replace(".pending", ".done")
            marker["processed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            # 原子写 .done
            tmp_done = done_path + ".tmp"
            with open(tmp_done, "w", encoding="utf-8") as f:
                json.dump(marker, f, ensure_ascii=False, indent=2)
            os.replace(tmp_done, done_path)

            # 删除 .pending
            pending_file.unlink()

            processed += 1
            scan_log.info(f"Successfully processed: {video_path}")

        except Exception as e:
            scan_log.error(f"Processing failed for {pending_file}: {e}")
            # .pending 保留，下次重试

    return processed


def run_watcher(interval: int = 30):
    """持续监控 .pending 文件。在 PC 上以独立进程运行。

    Args:
        interval: 扫描间隔（秒），默认 30 秒
    """
    scan_log.info("Watcher started. Monitoring for .pending files...")

    while True:
        try:
            count = process_pending_videos()
            if count > 0:
                scan_log.info(f"Processed {count} video(s)")
        except Exception as e:
            scan_log.error(f"Watcher error: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    run_watcher()