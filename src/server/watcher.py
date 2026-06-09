# Copyright (c) 2024 bilive.
# PC 端 watcher — 监控 NFS 共享目录中的 .pending 标记文件
#
# 工作流程:
# 1. 扫描 VIDEOS_DIR 下的 *.pending 文件
# 2. 读取标记中的相对路径，拼接 PC 本地绝对路径
# 3. 调用唯一支持的 slice_only 处理管线
# 4. 成功后将 .pending 改为 .done，写 `.mp4.task.json` 历史
# 5. 失败则写 `.mp4.task.json` (status=failed)，删除 .pending（不再自动重试）

import argparse
import json
import os
import time
from pathlib import Path

from src.config.server_config import VIDEOS_DIR
from src.log.logger import scan_log
from src.burn.task_history import write_task_history


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
        video_path = ""
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

            started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            worker_pid = os.getpid()

            # 读标记中的 slice_options（burst 参数覆盖）
            slice_options = marker.get("slice_options", {}) or {}

            # 执行唯一支持的切片处理管线
            pipeline_result = {}
            if action == "slice":
                from src.burn.slice_only import slice_only
                result = slice_only(video_path, **slice_options)
                if isinstance(result, dict):
                    pipeline_result = result
                if pipeline_result.get("status") == "failed":
                    raise RuntimeError(pipeline_result.get("error") or "slice pipeline failed")
            else:
                raise ValueError(f"Unknown action: {action}")

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

            # 写任务历史
            write_task_history(
                video_path,
                status="skipped" if pipeline_result.get("status") == "skipped" else "done",
                videos_root=videos_dir,
                started_at=started_at,
                worker_pid=worker_pid,
                slice_count=int(pipeline_result.get("slice_count") or 0),
                output_slices=_relative_output_slices(
                    pipeline_result.get("output_slices"),
                    videos_dir,
                ),
                segments=pipeline_result.get("segments"),
                diagnostics=pipeline_result.get("diagnostics"),
            )

            processed += 1
            scan_log.info(f"Successfully processed: {video_path}")

        except Exception as e:
            scan_log.error(f"Processing failed for {pending_file}: {e}")
            # 写失败历史并移除 pending（不再自动重试，需手动 requeue）
            try:
                if video_path and os.path.exists(video_path):
                    write_task_history(
                        video_path,
                        status="failed",
                        videos_root=videos_dir,
                        error=str(e),
                    )
            except Exception:
                pass
            # 删除 pending，防止无限重试
            try:
                pending_file.unlink()
            except Exception:
                pass

    return processed


def _relative_output_slices(output_slices, videos_dir: Path):
    if not isinstance(output_slices, list):
        return None

    normalized = []
    root = Path(videos_dir).resolve()
    for item in output_slices:
        path_text = str(item)
        try:
            normalized.append(Path(path_text).resolve().relative_to(root).as_posix())
        except (OSError, ValueError):
            normalized.append(path_text.replace("\\", "/"))
    return normalized


def run_watcher(interval: int = 30, videos_dir: str = None):
    """持续监控 .pending 文件。在 PC 上以独立进程运行。

    Args:
        interval: 扫描间隔（秒），默认 30 秒
    """
    scan_log.info("Watcher started. Monitoring for .pending files...")

    while True:
        try:
            count = process_pending_videos(videos_dir)
            if count > 0:
                scan_log.info(f"Processed {count} video(s)")
        except Exception as e:
            scan_log.error(f"Watcher error: {e}")

        time.sleep(interval)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Process pending bilive tasks.")
    parser.add_argument("--once", action="store_true", help="process pending tasks once and exit")
    parser.add_argument("--interval", type=int, default=30, help="seconds between scans")
    parser.add_argument("--videos-dir", default=None, help="override videos root")
    args = parser.parse_args(argv)

    if args.once:
        count = process_pending_videos(args.videos_dir)
        scan_log.info(f"One-shot worker complete. Processed {count} video(s).")
        return 0

    run_watcher(interval=args.interval, videos_dir=args.videos_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
