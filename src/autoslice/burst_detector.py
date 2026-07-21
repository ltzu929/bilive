# Copyright (c) 2024 bilive.
# 弹幕突增检测算法 — 替代固定窗口密度，检测弹幕突然爆发的时段

from dataclasses import dataclass
from collections import defaultdict
from typing import Any, Callable, List, Tuple
import statistics

from src.log.logger import scan_log


@dataclass
class BurstEvent:
    """一个弹幕突增事件"""
    peak_time: float        # 峰值时刻（秒）
    start: float            # 切片起始时间（秒）
    end: float              # 切片结束时间（秒）
    duration: float         # 切片总时长（秒）
    peak_density: float     # 峰值密度（弹幕数/窗口秒数）
    burst_ratio: float      # 峰值突增率（相对背景）
    danmaku_count: int      # 切片区间内弹幕总数
    baseline_density: float = 0.0   # 背景密度基线（弹幕数/秒）
    local_density: float = 0.0      # 峰值局部密度（弹幕数/秒）


def build_density_series(
    timestamps: List[float],
    video_duration: float,
) -> Tuple[List[int], float]:
    """将弹幕时间戳转为 1s 粒度的密度序列

    Args:
        timestamps: 弹幕时间戳列表（秒）
        video_duration: 视频总时长（秒）

    Returns:
        (density_series, duration) — density_series[i] 是第 i 秒的弹幕数
    """
    if not timestamps or video_duration <= 0:
        return [], 0.0

    duration = int(video_duration) + 1
    density = [0] * duration
    for t in timestamps:
        idx = int(t)
        if 0 <= idx < duration:
            density[idx] += 1
    return density, float(duration)


def compute_baseline(density: List[int], skip_head: int = 300, skip_tail: int = 300) -> float:
    """计算背景密度基线（中位数）

    跳过开头和结尾各 skip_head/skip_tail 秒，避免异常值。
    如果全部为 0，返回 1.0 避免除零。
    """
    start = skip_head
    end = len(density) - skip_tail if len(density) > skip_head + skip_tail else len(density)
    middle = density[start:end]

    if not middle:
        return 1.0

    nonzero = [d for d in middle if d > 0]
    if not nonzero:
        return 1.0

    return float(statistics.median(nonzero))


def detect_bursts(
    timestamps: List[float],
    video_duration: float,
    burst_ratio: float = 3.0,
    burst_window: int = 10,
    context: int = 60,
    merge_gap: int = 5,
    top_n: int = 3,
    lag_seconds: float = 0.0,
    diagnostics_callback: Callable[[dict[str, Any]], None] | None = None,
) -> List[BurstEvent]:
    """弹幕突增检测主函数

    Args:
        timestamps: 弹幕时间戳列表（秒），从 ASS 文件提取
        video_duration: 视频总时长（秒）
        burst_ratio: 突增阈值，局部密度/背景密度 ≥ 此值视为突增
        burst_window: 突增检测窗口大小（秒）
        context: 峰值前后各取的秒数，切片总长 = 2 × context
        merge_gap: 相邻突增事件合并间隔（秒）
        top_n: 最多选几个突增事件
        lag_seconds: 弹幕相对真实爆点的滞后补偿（秒）。弹幕密度峰值通常
            比真实爆点晚数秒，切窗锚点前移 lag_seconds 以对齐真实爆点。
            默认 0.0 表示不补偿。

    Returns:
        按 peak_density 降序排列的 BurstEvent 列表
    """
    if not timestamps or video_duration <= 0:
        scan_log.warning("No timestamps or invalid duration for burst detection")
        _emit_diagnostics(
            diagnostics_callback,
            danmaku_count=len(timestamps or []),
            duration_seconds=video_duration,
            burst_ratio=burst_ratio,
            burst_window=burst_window,
            context=context,
            baseline_density=0.0,
            detected_segments=0,
            selected_bursts=0,
            reason="没有弹幕时间戳或视频时长无效",
        )
        return []

    scan_log.info(
        f"Burst detection: {len(timestamps)} danmaku, "
        f"duration={video_duration:.1f}s, burst_ratio={burst_ratio}, "
        f"window={burst_window}s, context={context}s"
    )

    # 1. 构建 1s 粒度密度序列
    density, dur = build_density_series(timestamps, video_duration)
    if not density:
        return []

    # 2. 计算基线
    baseline = compute_baseline(density)
    scan_log.info(f"Baseline density: {baseline:.2f} danmaku/s")

    # 3. 滑动窗口计算局部密度
    n = len(density)
    half_win = burst_window // 2
    local_densities = []

    for i in range(n):
        win_start = max(0, i - half_win)
        win_end = min(n, i + half_win + 1)
        local_sum = sum(density[win_start:win_end])
        local_density = local_sum / float(win_end - win_start)
        local_densities.append(local_density)

    # 4. 标记突增事件（局部密度/基线 ≥ burst_ratio）
    burst_flags = [False] * n
    for i in range(n):
        if baseline > 0 and local_densities[i] / baseline >= burst_ratio:
            burst_flags[i] = True

    # 5. 合并相邻突增事件
    segments = []
    in_segment = False
    seg_start = 0

    for i in range(n):
        if burst_flags[i] and not in_segment:
            seg_start = i
            in_segment = True
        elif not burst_flags[i] and in_segment:
            segments.append((seg_start, i))
            in_segment = False
    if in_segment:
        segments.append((seg_start, n))

    # 合并间隔 < merge_gap 的相邻段
    merged = []
    for seg in segments:
        if merged and seg[0] - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(seg)

    if not merged:
        scan_log.info("No burst events detected")
        _emit_diagnostics(
            diagnostics_callback,
            danmaku_count=len(timestamps),
            duration_seconds=video_duration,
            burst_ratio=burst_ratio,
            burst_window=burst_window,
            context=context,
            baseline_density=baseline,
            detected_segments=0,
            selected_bursts=0,
            reason="未检测到超过阈值的弹幕突增",
        )
        return []

    scan_log.info(f"Detected {len(merged)} burst segments before top_n filtering")

    # 6. 为每个突增段找到峰值，生成切片
    events = []
    for seg_start, seg_end in merged:
        # 找峰值的弹幕密度（用1s粒度）
        peak_idx = seg_start
        peak_val = 0
        for i in range(seg_start, min(seg_end, n)):
            if density[i] > peak_val:
                peak_val = density[i]
                peak_idx = i

        peak_time = float(peak_idx)
        peak_local_density = local_densities[peak_idx] if peak_idx < len(local_densities) else 0.0
        ratio = peak_local_density / baseline if baseline > 0 else 0.0

        # 弹幕密度峰值滞后于真实爆点，切窗锚点前移 lag_seconds 对齐真实爆点
        anchor = max(0.0, peak_time - lag_seconds)

        # 切片范围：爆点锚点前后各 context 秒
        slice_start = max(0.0, anchor - context)
        slice_end = min(video_duration, anchor + context)

        # 如果靠边缘，向非边缘方向补齐
        if anchor < context:
            slice_start = 0.0
            slice_end = min(video_duration, 2 * context)
        if anchor + context > video_duration:
            slice_end = video_duration
            slice_start = max(0.0, video_duration - 2 * context)

        duration = slice_end - slice_start

        # 计算切片区间内弹幕总数
        dmk_count = sum(density[int(slice_start):int(slice_end) + 1])

        events.append(BurstEvent(
            peak_time=peak_time,
            start=slice_start,
            end=slice_end,
            duration=duration,
            peak_density=peak_local_density,
            burst_ratio=ratio,
            danmaku_count=dmk_count,
            baseline_density=baseline,
            local_density=peak_local_density,
        ))

    # 7. 按 peak_density 降序取 top_n
    events.sort(key=lambda e: e.peak_density, reverse=True)

    # 去重：切片重叠超过 30s 则只保留密度更高的
    selected = []
    for event in events:
        overlap_too_much = False
        for sel in selected:
            overlap_start = max(event.start, sel.start)
            overlap_end = min(event.end, sel.end)
            overlap = overlap_end - overlap_start
            if overlap > context:  # 重叠超过一个 context（60s）
                overlap_too_much = True
                break
        if not overlap_too_much:
            selected.append(event)
        if len(selected) >= top_n:
            break

    for i, evt in enumerate(selected):
        scan_log.info(
            f"Burst #{i+1}: peak={evt.peak_time:.1f}s, "
            f"slice=[{evt.start:.1f}s, {evt.end:.1f}s], "
            f"duration={evt.duration:.1f}s, "
            f"ratio={evt.burst_ratio:.1f}x, "
            f"danmaku={evt.danmaku_count}"
        )

    _emit_diagnostics(
        diagnostics_callback,
        danmaku_count=len(timestamps),
        duration_seconds=video_duration,
        burst_ratio=burst_ratio,
        burst_window=burst_window,
        context=context,
        baseline_density=baseline,
        detected_segments=len(merged),
        selected_bursts=len(selected),
        max_burst_ratio=max((event.burst_ratio for event in selected), default=0.0),
        reason=f"检测到 {len(selected)} 个可切片爆点",
    )
    return selected


def _emit_diagnostics(callback, **payload) -> None:
    if callback:
        callback(payload)
