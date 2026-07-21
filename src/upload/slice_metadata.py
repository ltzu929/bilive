# Copyright (c) 2024 bilive.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def slice_upload_metadata_path(video_path: str | Path) -> Path:
    return Path(video_path).with_suffix(".upload.json")


def slice_features_path(video_path: str | Path) -> Path:
    return Path(video_path).with_suffix(".features.json")


# Feature columns captured at slice-generation time and later joined with
# published B站 stats in the slice_performance table (Phase 3).
SLICE_FEATURE_FIELDS = (
    "title",
    "quality_score",
    "completeness_score",
    "burst_ratio",
    "burst_context",
    "lag_seconds",
    "danmaku_count",
    "trim_duration",
    "context_start",
    "context_end",
)


def write_slice_features(
    video_path: str | Path,
    features: dict[str, Any],
) -> Path:
    path = slice_features_path(video_path)
    payload = {
        key: features[key]
        for key in SLICE_FEATURE_FIELDS
        if key in features and features[key] is not None
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def read_slice_features(video_path: str | Path) -> dict[str, Any] | None:
    path = slice_features_path(video_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def delete_slice_features(video_path: str | Path) -> None:
    path = slice_features_path(video_path)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def write_slice_upload_metadata(
    video_path: str | Path,
    *,
    title: str,
    desc: str = "",
    tag: str | list[str] = "直播切片",
    source: str = "https://live.bilibili.com/",
    cover: str = "",
    dynamic: str = "",
) -> Path:
    path = slice_upload_metadata_path(video_path)
    path.write_text(
        json.dumps(
            {
                "title": title,
                "desc": desc,
                "tag": _normalize_tag(tag),
                "source": source,
                "cover": cover,
                "dynamic": dynamic,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def read_slice_upload_metadata(video_path: str | Path) -> dict[str, Any] | None:
    path = slice_upload_metadata_path(video_path)
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def delete_slice_upload_metadata(video_path: str | Path) -> None:
    path = slice_upload_metadata_path(video_path)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def is_slice_upload(video_path: str | Path) -> bool:
    return str(video_path).lower().endswith(".flv") or read_slice_upload_metadata(video_path) is not None


def _normalize_tag(tag: str | list[str]) -> str:
    if isinstance(tag, list):
        values = [str(item).strip() for item in tag if str(item).strip()]
        return ",".join(values) or "直播切片"
    return str(tag or "直播切片")
