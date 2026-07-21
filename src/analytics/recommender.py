# Copyright (c) 2024 bilive.
"""Advisory-only tuning recommender (pure functions, Windows side).

Reads ``slice_performance`` rows (feature snapshot + post-publish stats) and
correlates *what we tuned* with *how the slice performed*. It emits a report,
suggested config deltas, and a few-shot pack of top performers. It NEVER
mutates the live configuration — a human or an explicit switch decides whether
to fold the suggestions back into ``bilive-server.toml``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


# feature column -> config key path that tuning would touch
TUNABLE_FEATURES: tuple[tuple[str, str], ...] = (
    ("lag_seconds", "slice.burst.burst_lag_seconds"),
    ("burst_ratio", "slice.burst.burst_ratio"),
    ("burst_context", "slice.burst.burst_context"),
    ("quality_score", "slice.mimo.min_quality_score"),
)

# interaction columns used to derive an engagement rate
_INTERACTION_COLUMNS = ("likes", "coin", "favorite", "share", "reply", "danmaku")

# few-shot descriptive fields, included when present on the row
_FEW_SHOT_TEXT_FIELDS = ("title", "topic_summary", "why_viewer_would_watch")


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    collected = [v for v in values if v is not None]
    if not collected:
        return None
    return sum(collected) / len(collected)


def _performance_score(row: dict[str, Any]) -> float:
    view = _to_float(row.get("view"))
    if view is not None:
        return view
    total = 0.0
    seen = False
    for column in _INTERACTION_COLUMNS:
        value = _to_float(row.get(column))
        if value is not None:
            total += value
            seen = True
    return total if seen else 0.0


def _engagement_rate(row: dict[str, Any]) -> float | None:
    view = _to_float(row.get("view"))
    if not view:
        return None
    interactions = 0.0
    for column in ("likes", "coin", "favorite", "share"):
        value = _to_float(row.get(column))
        if value is not None:
            interactions += value
    return interactions / view


def _has_performance(row: dict[str, Any]) -> bool:
    if _to_float(row.get("view")) is not None:
        return True
    return any(_to_float(row.get(col)) is not None for col in _INTERACTION_COLUMNS)


def build_recommendations(
    rows: list[dict[str, Any]],
    *,
    current_config: dict[str, Any] | None = None,
    min_samples: int = 5,
    top_ratio: float = 0.3,
    few_shot_limit: int = 8,
) -> dict[str, Any]:
    """Correlate features with performance and produce advisory suggestions.

    Args:
        rows: ``slice_performance`` rows (feature snapshot + stats).
        current_config: optional flat map of ``config.key.path`` -> value, used
            to annotate suggestions with the current live value.
        min_samples: minimum rows with performance data before advising.
        top_ratio: fraction of best performers used as the "good" cohort.
        few_shot_limit: max entries in the few-shot pack.
    """
    current_config = current_config or {}
    usable = [row for row in rows if _has_performance(row)]
    usable.sort(key=_performance_score, reverse=True)

    report: dict[str, Any] = {
        "sample_size": len(usable),
        "insufficient_data": len(usable) < max(1, min_samples),
        "metrics": {},
        "config_suggestions": {},
        "few_shot": [],
    }
    if report["insufficient_data"]:
        return report

    top_count = max(1, round(len(usable) * top_ratio))
    top_rows = usable[:top_count]

    for feature, config_key in TUNABLE_FEATURES:
        overall_mean = _mean(_to_float(row.get(feature)) for row in usable)
        top_mean = _mean(_to_float(row.get(feature)) for row in top_rows)
        if overall_mean is None or top_mean is None:
            continue
        entry: dict[str, Any] = {
            "config_key": config_key,
            "overall_mean": round(overall_mean, 4),
            "top_mean": round(top_mean, 4),
            "delta": round(top_mean - overall_mean, 4),
        }
        if config_key in current_config:
            entry["current"] = current_config[config_key]
        report["metrics"][feature] = entry
        # Advisory suggestion: nudge the config toward the top-performer mean.
        report["config_suggestions"][config_key] = round(top_mean, 4)

    for row in top_rows[:few_shot_limit]:
        example: dict[str, Any] = {}
        for field_name in _FEW_SHOT_TEXT_FIELDS:
            value = row.get(field_name)
            if value:
                example[field_name] = value
        view = _to_float(row.get("view"))
        if view is not None:
            example["view"] = int(view)
        rate = _engagement_rate(row)
        if rate is not None:
            example["engagement_rate"] = round(rate, 4)
        if example:
            report["few_shot"].append(example)

    return report


def write_recommendations(report: dict[str, Any], out_dir: str | Path) -> dict[str, Path]:
    """Persist the report and few-shot pack as JSON. Returns the written paths."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / "recommendations.json"
    few_shot_path = directory / "few_shot.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    few_shot_path.write_text(
        json.dumps(report.get("few_shot", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report_path, "few_shot": few_shot_path}
