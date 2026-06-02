# Copyright (c) 2024 bilive.

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


PHASE_LABELS = {
    "idle": "空闲",
    "queued": "已排队",
    "start": "准备切片",
    "info": "读取信息",
    "detect": "检测高能片段",
    "slice": "切片中",
    "analyze": "分析标题",
    "metadata": "写入元数据",
    "queue": "加入上传队列",
    "cleanup": "清理源文件",
    "complete": "完成",
    "error": "错误",
}


LEGACY_PHASE_LABELS = {
    "Idle": "空闲",
    "Queued": "已排队",
    "Starting": "准备切片",
    "Info": "读取信息",
    "Detecting": "检测高能片段",
    "Slicing": "切片中",
    "Analyzing": "分析标题",
    "Metadata": "写入元数据",
    "Queue": "加入上传队列",
    "Cleanup": "清理源文件",
    "Complete": "完成",
    "Error": "错误",
}


LEGACY_MESSAGES = {
    "No active slicing task": "暂无切片任务",
    "Slice processing complete": "切片处理完成",
    "Preparing slice task": "准备切片任务",
    "Reading recording info": "读取录制信息",
    "Detecting highlight segments": "正在检测弹幕突增片段",
    "Writing upload metadata": "正在写入上传参数",
    "Adding clip to upload queue": "正在加入上传队列",
    "Cleaning source files": "正在清理源文件",
    "Waiting for the PC-side slice worker": "等待本机 PC 切片 worker 处理",
}


DEFAULT_STATE = {
    "status": "idle",
    "phase": "idle",
    "phase_label": PHASE_LABELS["idle"],
    "room_id": "",
    "source_path": "",
    "source_name": "",
    "current_slice": 0,
    "total_slices": 0,
    "current_slice_path": "",
    "current_slice_percent": 0.0,
    "message": "暂无切片任务",
    "error": "",
    "diagnostics": [],
    "updated_at": 0.0,
    "stale": False,
}


def default_progress_path() -> Path:
    project_dir = Path(
        os.environ.get(
            "BILIVE_RUNTIME_DIR",
            os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2]),
        )
    )
    return project_dir / "logs" / "runtime" / "slice-progress.json"


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 1)))


def parse_ffmpeg_progress_line(line: str, duration_seconds: float) -> Optional[float]:
    if duration_seconds <= 0:
        return None
    key, separator, value = line.strip().partition("=")
    if not separator:
        return None

    seconds = None
    try:
        if key == "out_time_ms":
            seconds = float(value) / 1_000_000.0
        elif key == "out_time":
            seconds = _parse_ffmpeg_time(value)
    except ValueError:
        return None

    if seconds is None:
        return None
    return clamp_percent((seconds / float(duration_seconds)) * 100.0)


def load_progress_state(
    path: str | Path | None = None,
    stale_after_seconds: float = 180.0,
) -> dict[str, Any]:
    progress_path = Path(path) if path is not None else default_progress_path()
    if not progress_path.is_file():
        return dict(DEFAULT_STATE)

    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_STATE)

    state = _normalize_state(data)
    updated_at = float(state.get("updated_at") or 0.0)
    state["stale"] = (
        state["status"] == "running"
        and updated_at > 0
        and time.time() - updated_at > stale_after_seconds
    )
    return state


class SliceProgressWriter:
    def __init__(
        self,
        path: str | Path | None = None,
        min_interval_seconds: float = 0.5,
    ) -> None:
        self.path = Path(path) if path is not None else default_progress_path()
        self.state = dict(DEFAULT_STATE)
        self.min_interval_seconds = min_interval_seconds
        self._last_write_at = 0.0

    def update(self, force: bool = False, **fields: Any) -> dict[str, Any]:
        self.state.update(fields)
        self.state["updated_at"] = time.time()
        state = _normalize_state(self.state)

        now = time.monotonic()
        if not force and now - self._last_write_at < self.min_interval_seconds:
            self.state = state
            return state

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

        self._last_write_at = now
        self.state = state
        return state

    def error(self, message: str, **fields: Any) -> dict[str, Any]:
        return self.update(
            force=True,
            status="error",
            phase="error",
            phase_label=PHASE_LABELS["error"],
            error=message,
            message=message,
            **fields,
        )

    def complete(self, message: str = "切片处理完成", **fields: Any) -> dict[str, Any]:
        return self.update(
            force=True,
            status="complete",
            phase="complete",
            phase_label=PHASE_LABELS["complete"],
            message=message,
            current_slice_percent=100.0,
            **fields,
        )


def _normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    state.update(data)
    state["status"] = str(state.get("status") or "idle")
    state["phase"] = str(state.get("phase") or "idle")
    phase_label = str(
        data.get("phase_label") or PHASE_LABELS.get(state["phase"], state["phase"])
    )
    state["phase_label"] = LEGACY_PHASE_LABELS.get(phase_label, phase_label)
    state["current_slice"] = _as_int(state.get("current_slice"))
    state["total_slices"] = _as_int(state.get("total_slices"))
    state["current_slice_percent"] = clamp_percent(
        _as_float(state.get("current_slice_percent"))
    )
    state["updated_at"] = _as_float(state.get("updated_at"))
    state["stale"] = bool(state.get("stale", False))
    state["diagnostics"] = _normalize_diagnostics(state.get("diagnostics"))

    for key in [
        "room_id",
        "source_path",
        "source_name",
        "current_slice_path",
        "message",
        "error",
    ]:
        value = str(state.get(key) or "")
        if key == "message":
            value = LEGACY_MESSAGES.get(value, value)
        state[key] = value

    return state


def _normalize_diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        details = item.get("details")
        if not isinstance(details, list):
            details = []
        normalized_details = []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            normalized_details.append(
                {
                    "label": str(detail.get("label") or ""),
                    "value": str(detail.get("value") or ""),
                }
            )
        items.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "status": str(item.get("status") or "info"),
                "message": str(item.get("message") or ""),
                "details": normalized_details,
            }
        )
    return items


def _parse_ffmpeg_time(value: str) -> Optional[float]:
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
