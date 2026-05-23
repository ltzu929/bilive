# Copyright (c) 2024 bilive.

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


DEFAULT_STATE = {
    "status": "idle",
    "phase": "idle",
    "phase_label": "空闲",
    "room_id": "",
    "source_path": "",
    "source_name": "",
    "current_slice": 0,
    "total_slices": 0,
    "current_slice_path": "",
    "current_slice_percent": 0.0,
    "message": "暂无切片任务",
    "error": "",
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
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_progress_path()
        self.state = dict(DEFAULT_STATE)

    def update(self, **fields: Any) -> dict[str, Any]:
        self.state.update(fields)
        self.state["updated_at"] = time.time()
        state = _normalize_state(self.state)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

        self.state = state
        return state

    def error(self, message: str, **fields: Any) -> dict[str, Any]:
        return self.update(
            status="error",
            phase="error",
            phase_label="失败",
            error=message,
            message=message,
            **fields,
        )

    def complete(self, message: str = "切片处理完成", **fields: Any) -> dict[str, Any]:
        return self.update(
            status="complete",
            phase="complete",
            phase_label="完成",
            message=message,
            current_slice_percent=100.0,
            **fields,
        )


def _normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    state.update(data)
    state["status"] = str(state.get("status") or "idle")
    state["phase"] = str(state.get("phase") or "idle")
    state["phase_label"] = str(state.get("phase_label") or state["phase"])
    state["current_slice"] = _as_int(state.get("current_slice"))
    state["total_slices"] = _as_int(state.get("total_slices"))
    state["current_slice_percent"] = clamp_percent(
        _as_float(state.get("current_slice_percent"))
    )
    state["updated_at"] = _as_float(state.get("updated_at"))
    state["stale"] = bool(state.get("stale", False))

    for key in [
        "room_id",
        "source_path",
        "source_name",
        "current_slice_path",
        "message",
        "error",
    ]:
        state[key] = str(state.get(key) or "")

    return state


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
