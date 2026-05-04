# Copyright (c) 2024 bilive.
# 独立切片流程：跳过整场直播渲染，直接切片上传

import os
from src.config import (
    AUTO_SLICE,
    SLICE_DURATION,
    MIN_VIDEO_SIZE,
    SLICE_NUM,
    SLICE_OVERLAP,
    SLICE_STEP,
)
from src.danmaku.generate_danmakus import get_resolution, process_danmakus
from autoslice import slice_video_by_danmaku
from src.autoslice.inject_metadata import inject_metadata
from src.autoslice.title_generator import generate_title
from src.upload.extract_video_info import get_video_info
from src.log.logger import scan_log
from db.conn import insert_upload_queue


def check_file_size(file_path):
    """检查文件大小（MB）"""
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    return file_size_mb


def slice_only(video_path):
    """独立切片流程：不渲染整场直播，直接切片上传

    Args:
        video_path: 录制的视频文件路径（mp4）

    流程：
    1. 弹幕转换（xml → ass）
    2. 弹幕密度切片（使用原始视频）
    3. 标题生成 + 质量筛选
    4. 上传切片
    5. 清理原始文件
    """
    if not os.path.exists(video_path):
        scan_log.error(f"File {video_path} does not exist.")
        return

    original_video_path = str(video_path)
    xml_path = original_video_path[:-4] + ".xml"
    ass_path = original_video_path[:-4] + ".ass"

    # 检查弹幕文件是否存在
    if not os.path.exists(xml_path):
        scan_log.warning(f"No danmaku file for {video_path}, cannot slice by density.")
        return

    # 检查视频大小是否满足切片阈值
    if check_file_size(original_video_path) < MIN_VIDEO_SIZE:
        scan_log.info(f"Video size too small ({check_file_size(original_video_path)}MB), skip slicing: {original_video_path}")
        return

    scan_log.info(f"Starting slice-only processing: {original_video_path}")

    # 1. 弹幕转换（xml → ass）
    try:
        resolution_x, resolution_y = get_resolution(original_video_path)
        process_danmakus(xml_path, resolution_x, resolution_y)
        scan_log.info(f"Danmaku converted: {ass_path}")
    except Exception as e:
        scan_log.error(f"Error in process_danmakus: {e}")
        return

    # 2. 获取主播信息（用于生成标题）
    title, artist, date = get_video_info(original_video_path)

    # 3. 弹幕密度切片（使用原始视频，不渲染）
    try:
        slices_path = slice_video_by_danmaku(
            ass_path,
            original_video_path,  # 使用原始视频，而非渲染后的视频
            SLICE_DURATION,
            SLICE_NUM,
            SLICE_OVERLAP,
            SLICE_STEP,
        )
        scan_log.info(f"Generated {len(slices_path)} slices")
    except Exception as e:
        scan_log.error(f"Error in slice_video_by_danmaku: {e}")
        return

    # 4. 处理每个切片：标题生成 + 质量筛选 + 上传
    for slice_path in slices_path:
        try:
            result = generate_title(slice_path, artist)

            if result is None:
                scan_log.error(f"Failed to generate title for {slice_path}")
                os.remove(slice_path)
                continue

            # 检查是否为 AnalysisResult 对象（local-audio/omni 模式）
            from src.autoslice.analysis_result import AnalysisResult
            if isinstance(result, AnalysisResult):
                # 保存分析结果 JSON（供 MCP 剪辑使用）
                from src.config import OMNI_ENABLE_DEEP_ANALYSIS
                if OMNI_ENABLE_DEEP_ANALYSIS:
                    analysis_json_path = slice_path[:-4] + "_analysis.json"
                    result.to_json_file(analysis_json_path)
                    scan_log.info(f"Analysis result saved: {analysis_json_path}")

                # 质量筛选
                from src.config import OMNI_ENABLE_QUALITY_FILTER, OMNI_QUALITY_THRESHOLD
                from src.autoslice.slice_quality_filter import should_retain_slice
                if OMNI_ENABLE_QUALITY_FILTER and not should_retain_slice(result, OMNI_QUALITY_THRESHOLD):
                    scan_log.info(f"Slice filtered by quality (score={result.quality_score}), removing: {slice_path}")
                    os.remove(slice_path)
                    continue

                slice_title = result.title
            else:
                # 传统模型返回标题字符串
                slice_title = result

            # 注入标题元数据，输出为 .flv 格式（标记为切片）
            slice_video_flv_path = slice_path[:-4] + ".flv"
            inject_metadata(slice_path, slice_title, slice_video_flv_path)
            os.remove(slice_path)

            # 加入上传队列；本地测试时可跳过，避免误传整场调试产物。
            if os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1":
                scan_log.info(f"Skip upload queue for local test: {slice_video_flv_path}")
            elif not insert_upload_queue(slice_video_flv_path):
                scan_log.error(f"Cannot insert slice to upload queue: {slice_video_flv_path}")
            else:
                scan_log.info(f"Slice ready for upload: {slice_video_flv_path}")

        except Exception as e:
            scan_log.error(f"Error processing slice {slice_path}: {e}")
            if os.path.exists(slice_path):
                os.remove(slice_path)

    # 5. 清理原始文件（录制文件 + 弹幕文件）
    if os.getenv("BILIVE_KEEP_SOURCE") == "1":
        scan_log.info("BILIVE_KEEP_SOURCE=1, keep original video/danmaku files.")
    else:
        for remove_path in [original_video_path, xml_path, ass_path]:
            if os.path.exists(remove_path):
                os.remove(remove_path)
                scan_log.info(f"Removed: {remove_path}")

    scan_log.info(f"Slice-only processing complete for: {original_video_path}")
