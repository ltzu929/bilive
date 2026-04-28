# src/autoslice/slice_quality_filter.py
# Copyright (c) 2024 bilive.

from typing import Optional
from src.autoslice.analysis_result import AnalysisResult
from src.log.logger import scan_log


def should_retain_slice(result: Optional[AnalysisResult], threshold: float = 0.6) -> bool:
    """判断切片是否值得保留

    Args:
        result: OMNI 分析结果
        threshold: 质量阈值（0-1）

    Returns:
        bool: True 表示保留，False 表示跳过
    """
    if result is None:
        scan_log.warning("Analysis result is None, skipping slice")
        return False

    # 直接使用 OMNI 的推荐判断
    if not result.retain_recommendation:
        scan_log.info(f"Slice not recommended: {result.quality_reason}")
        return False

    # 结合阈值判断
    if result.quality_score < threshold:
        scan_log.info(f"Quality score {result.quality_score} below threshold {threshold}")
        return False

    scan_log.info(f"Slice passed quality filter: score={result.quality_score}")
    return True