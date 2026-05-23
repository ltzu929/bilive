# Slice Progress Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `/tasks` 页面显示自动切片的流水线阶段和当前 ffmpeg 切片百分比。

**Architecture:** 切片进程把当前状态原子写入 `logs/runtime/slice-progress.json`，FastAPI 通过 `/api/slice-progress` 暴露标准化状态，静态前端每 2 秒轮询并渲染紧凑进度条。进度文件位于 SMB/CIFS 项目运行目录，避免写入 Pi SD 卡。

**Tech Stack:** Python 3、FastAPI、pytest/httpx、原生 HTML/CSS/JavaScript、ffmpeg `-progress pipe:1`。

---

## 文件结构

- Create: `src/burn/slice_progress.py`
  负责进度状态模型、进度文件路径、原子写入、读取标准化、ffmpeg 进度行解析。
- Modify: `src/autoslice/auto_slice_video/autosv/slice/slice_video.py`
  给 ffmpeg 命令增加 `-progress pipe:1`，解析当前片段百分比，并通过回调上报。
- Modify: `src/autoslice/danmaku_slice.py`
  给 `slice_video_by_danmaku()` 增加可选进度回调，在 density/burst 两种模式中报告第 N/M 个切片。
- Modify: `src/burn/slice_only.py`
  在流水线关键阶段写入进度状态，捕获错误时写入 error 状态，完成时写入 complete 状态。
- Modify: `src/dashboard/app.py`
  新增 `/api/slice-progress`。
- Modify: `frontend/index.html`
  在工具栏下方添加切片进度区域。
- Modify: `frontend/app.js`
  轮询 `/api/slice-progress` 并渲染 idle/running/complete/error 状态。
- Modify: `frontend/styles.css`
  增加进度区域样式，保持当前 Ant Design 风格。
- Test: `tests/test_slice_progress.py`
  覆盖进度解析、百分比夹取、状态文件读写。
- Test: `tests/test_dashboard_api.py`
  覆盖 progress API 的 idle/valid/stale/invalid JSON。
- Test: `tests/test_dashboard_frontend.py`
  覆盖前端包含 progress DOM、轮询 endpoint、渲染百分比。

---

### Task 1: 进度状态基础模块

**Files:**
- Create: `src/burn/slice_progress.py`
- Test: `tests/test_slice_progress.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_slice_progress.py` 新建以下测试：

```python
import json
import os
import time

from src.burn.slice_progress import (
    SliceProgressWriter,
    clamp_percent,
    default_progress_path,
    load_progress_state,
    parse_ffmpeg_progress_line,
)


def test_parse_ffmpeg_out_time_ms_to_percent():
    assert parse_ffmpeg_progress_line("out_time_ms=2500000", 10.0) == 25.0


def test_parse_ffmpeg_out_time_to_percent():
    assert parse_ffmpeg_progress_line("out_time=00:00:03.500000", 10.0) == 35.0


def test_clamp_percent_limits_range():
    assert clamp_percent(-10) == 0.0
    assert clamp_percent(120) == 100.0


def test_progress_writer_writes_atomic_json(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    writer = SliceProgressWriter(progress_path)

    writer.update(status="running", phase="danmaku", phase_label="弹幕转换", message="开始")

    data = json.loads(progress_path.read_text(encoding="utf-8"))
    assert data["status"] == "running"
    assert data["phase"] == "danmaku"
    assert data["phase_label"] == "弹幕转换"
    assert data["message"] == "开始"
    assert data["updated_at"]
    assert not progress_path.with_suffix(".json.tmp").exists()


def test_load_progress_state_returns_idle_when_missing(tmp_path):
    state = load_progress_state(tmp_path / "missing.json")

    assert state["status"] == "idle"
    assert state["phase"] == "idle"
    assert state["current_slice_percent"] == 0.0


def test_load_progress_state_marks_stale(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    old_updated = time.time() - 600
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "slice",
                "updated_at": old_updated,
            }
        ),
        encoding="utf-8",
    )

    state = load_progress_state(progress_path, stale_after_seconds=60)

    assert state["status"] == "running"
    assert state["stale"] is True


def test_load_progress_state_handles_invalid_json(tmp_path):
    progress_path = tmp_path / "slice-progress.json"
    progress_path.write_text("{", encoding="utf-8")

    state = load_progress_state(progress_path)

    assert state["status"] == "idle"
    assert state["phase"] == "idle"
    assert state["error"] == ""


def test_default_progress_path_uses_runtime_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))

    assert default_progress_path() == tmp_path / "logs" / "runtime" / "slice-progress.json"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py -q
```

Expected: `ModuleNotFoundError: No module named 'src.burn.slice_progress'` 或导入符号不存在。

- [ ] **Step 3: 实现最小进度模块**

创建 `src/burn/slice_progress.py`：

```python
# Copyright (c) 2024 bilive.

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


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
    project_dir = Path(os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2]))
    return project_dir / "logs" / "runtime" / "slice-progress.json"


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 1)))


def parse_ffmpeg_progress_line(line: str, duration_seconds: float) -> float | None:
    if duration_seconds <= 0:
        return None
    key, sep, value = line.strip().partition("=")
    if not sep:
        return None
    seconds = None
    if key == "out_time_ms":
        seconds = float(value) / 1_000_000.0
    elif key == "out_time":
        seconds = _parse_ffmpeg_time(value)
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
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        self.state = state
        return state

    def error(self, message: str, **fields: Any) -> dict[str, Any]:
        return self.update(status="error", phase="error", phase_label="失败", error=message, message=message, **fields)

    def complete(self, message: str = "切片处理完成", **fields: Any) -> dict[str, Any]:
        return self.update(status="complete", phase="complete", phase_label="完成", message=message, current_slice_percent=100.0, **fields)


def _normalize_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(DEFAULT_STATE)
    state.update(data)
    state["status"] = str(state.get("status") or "idle")
    state["phase"] = str(state.get("phase") or "idle")
    state["phase_label"] = str(state.get("phase_label") or state["phase"])
    state["current_slice"] = _as_int(state.get("current_slice"))
    state["total_slices"] = _as_int(state.get("total_slices"))
    state["current_slice_percent"] = clamp_percent(_as_float(state.get("current_slice_percent")))
    state["updated_at"] = _as_float(state.get("updated_at"))
    state["stale"] = bool(state.get("stale", False))
    for key in ["room_id", "source_path", "source_name", "current_slice_path", "message", "error"]:
        state[key] = str(state.get(key) or "")
    return state


def _parse_ffmpeg_time(value: str) -> float | None:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py -q
```

Expected: `7 passed`。

- [ ] **Step 5: 提交**

```powershell
git add src/burn/slice_progress.py tests/test_slice_progress.py
git commit -m "feat: add slice progress state helpers"
```

---

### Task 2: ffmpeg 当前片段进度

**Files:**
- Modify: `src/autoslice/auto_slice_video/autosv/slice/slice_video.py`
- Test: `tests/test_slice_progress.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_slice_progress.py`：

```python
from src.autoslice.auto_slice_video.autosv.slice import slice_video as slice_module


def test_slice_video_reports_ffmpeg_progress(monkeypatch, tmp_path):
    updates = []

    class FakeStdout:
        def __iter__(self):
            return iter(["out_time_ms=5000000\n", "progress=end\n"])

    class FakeProcess:
        stdout = FakeStdout()
        stderr = FakeStdout()

        def wait(self):
            return 0

    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(slice_module.subprocess, "Popen", fake_popen)

    slice_module.slice_video(
        str(tmp_path / "source.mp4"),
        str(tmp_path / "clip.mp4"),
        0,
        10,
        progress_callback=updates.append,
    )

    assert updates == [50.0, 100.0]
    assert "-progress" in commands[0]
    assert "pipe:1" in commands[0]
    assert "-nostats" in commands[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py::test_slice_video_reports_ffmpeg_progress -q
```

Expected: `TypeError`，因为 `slice_video()` 还不接受 `progress_callback`。

- [ ] **Step 3: 修改 `slice_video.py`**

将 `slice_video()` 改为使用 `Popen` 并解析 ffmpeg progress：

```python
# Copyright (c) 2024 bilive.
# Copyright (c) 2025 auto-slice-video

import subprocess
from typing import Callable

from src.burn.slice_progress import parse_ffmpeg_progress_line


def format_time(seconds):
    """Format seconds to hh:mm:ss."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"


def slice_video(video_path, output_path, start_time, duration, progress_callback: Callable[[float], None] | None = None):
    """Slice the video using ffmpeg."""
    duration_seconds = float(duration)
    formatted_duration = format_time(duration_seconds)
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-nostats",
        "-ss",
        format_time(start_time),
        "-i",
        video_path,
        "-t",
        formatted_duration,
        "-map_metadata",
        "-1",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        output_path,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.stdout:
        for line in process.stdout:
            percent = parse_ffmpeg_progress_line(line, duration_seconds)
            if percent is not None and progress_callback:
                progress_callback(percent)
    stderr = process.stderr.read() if process.stderr else ""
    return_code = process.wait()
    if return_code != 0:
        print(f"Error: {stderr}")
    elif progress_callback:
        progress_callback(100.0)
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py -q
```

Expected: `8 passed`。

- [ ] **Step 5: 提交**

```powershell
git add src/autoslice/auto_slice_video/autosv/slice/slice_video.py tests/test_slice_progress.py
git commit -m "feat: report ffmpeg slice progress"
```

---

### Task 3: 切片流水线状态写入

**Files:**
- Modify: `src/autoslice/danmaku_slice.py`
- Modify: `src/burn/slice_only.py`
- Test: `tests/test_slice_progress.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_slice_progress.py`：

```python
from pathlib import Path

from src.autoslice import danmaku_slice


def _write_minimal_ass(path: Path) -> None:
    path.write_text(
        "[Events]\n"
        "Dialogue: 0,00:00:01.00,00:00:02.00,Default,,0,0,0,,hello\n",
        encoding="utf-8",
    )


def test_slice_video_by_danmaku_reports_slice_callback(tmp_path, monkeypatch):
    ass_path = tmp_path / "source.ass"
    video_path = tmp_path / "source.mp4"
    _write_minimal_ass(ass_path)

    monkeypatch.setattr(
        danmaku_slice,
        "find_dense_periods",
        lambda log, timestamps, duration, top_n, max_overlap, step: [(10, 42)],
    )

    def fake_slice_video(video, output, start, duration, progress_callback=None):
        progress_callback(12.5)
        progress_callback(100.0)

    monkeypatch.setattr(danmaku_slice, "slice_video", fake_slice_video)
    events = []

    danmaku_slice.slice_video_by_danmaku(
        str(ass_path),
        str(video_path),
        duration=60,
        top_n=1,
        progress_callback=events.append,
    )

    assert events[0]["event"] == "slice_start"
    assert events[0]["current_slice"] == 1
    assert events[0]["total_slices"] == 1
    assert events[1]["event"] == "slice_progress"
    assert events[1]["percent"] == 12.5
    assert events[-1]["event"] == "slice_complete"
    assert events[-1]["percent"] == 100.0
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py::test_slice_video_by_danmaku_reports_slice_callback -q
```

Expected: `TypeError`，因为 `slice_video_by_danmaku()` 还不接受 `progress_callback`。

- [ ] **Step 3: 修改 `danmaku_slice.py`**

给 `slice_video_by_danmaku()` 和 `_slice_by_burst()` 增加 `progress_callback=None` 参数。在 density 循环中使用：

```python
    total_slices = len(dense_periods)
    for index, period in enumerate(dense_periods, start=1):
        ...
        if progress_callback:
            progress_callback({
                "event": "slice_start",
                "current_slice": index,
                "total_slices": total_slices,
                "output_path": output_name,
                "percent": 0.0,
            })
        slice_video(
            video_path,
            output_name,
            context_start,
            context_duration,
            progress_callback=lambda percent, idx=index, total=total_slices, path=output_name: progress_callback and progress_callback({
                "event": "slice_progress",
                "current_slice": idx,
                "total_slices": total,
                "output_path": path,
                "percent": percent,
            }),
        )
        if progress_callback:
            progress_callback({
                "event": "slice_complete",
                "current_slice": index,
                "total_slices": total_slices,
                "output_path": output_name,
                "percent": 100.0,
            })
```

在 burst 模式中对 `events` 使用同样结构：

```python
    total_slices = len(events)
    for i, event in enumerate(events):
        index = i + 1
        ...
        if progress_callback:
            progress_callback({
                "event": "slice_start",
                "current_slice": index,
                "total_slices": total_slices,
                "output_path": output_name,
                "percent": 0.0,
            })
        slice_video(
            video_path,
            output_name,
            event.start,
            event.duration,
            progress_callback=lambda percent, idx=index, total=total_slices, path=output_name: progress_callback and progress_callback({
                "event": "slice_progress",
                "current_slice": idx,
                "total_slices": total,
                "output_path": path,
                "percent": percent,
            }),
        )
        if progress_callback:
            progress_callback({
                "event": "slice_complete",
                "current_slice": index,
                "total_slices": total_slices,
                "output_path": output_name,
                "percent": 100.0,
            })
```

- [ ] **Step 4: 修改 `slice_only.py`**

在 `slice_only()` 开始处创建 writer：

```python
from pathlib import Path
from src.burn.slice_progress import SliceProgressWriter
```

```python
    progress = SliceProgressWriter()
    source_path = str(video_path)
    source_name = Path(source_path).name
    room_id = Path(source_path).parent.name
```

在主要阶段写入：

```python
    progress.update(
        status="running",
        phase="danmaku",
        phase_label="弹幕转换",
        room_id=room_id,
        source_path=source_path,
        source_name=source_name,
        message="正在转换弹幕",
    )
```

调用 `slice_video_by_danmaku()` 前写入 detect，调用时传入：

```python
        def on_slice_progress(event):
            progress.update(
                status="running",
                phase="slice",
                phase_label="切片中",
                room_id=room_id,
                source_path=source_path,
                source_name=source_name,
                current_slice=event.get("current_slice", 0),
                total_slices=event.get("total_slices", 0),
                current_slice_path=event.get("output_path", ""),
                current_slice_percent=event.get("percent", 0.0),
                message=f"正在切第 {event.get('current_slice', 0)}/{event.get('total_slices', 0)} 个片段",
            )
```

在生成标题、注入元数据、入队、清理和完成处分别写：

```python
            progress.update(status="running", phase="analyze", phase_label="分析标题", message=f"正在分析第 {index}/{len(slices_path)} 个片段", current_slice=index, total_slices=len(slices_path))
            progress.update(status="running", phase="metadata", phase_label="写入元数据", message="正在注入标题元数据")
            progress.update(status="running", phase="queue", phase_label="入上传队列", message="正在加入上传队列")
    progress.update(status="running", phase="cleanup", phase_label="清理源文件", message="正在清理源文件")
    progress.complete()
```

每个现有 `except Exception as e:` 分支在 `return` 前调用：

```python
        progress.error(str(e), source_path=source_path, source_name=source_name, room_id=room_id)
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py tests/test_slice_context.py -q
```

Expected: 所有测试通过。

- [ ] **Step 6: 提交**

```powershell
git add src/autoslice/danmaku_slice.py src/burn/slice_only.py tests/test_slice_progress.py
git commit -m "feat: write live slice pipeline progress"
```

---

### Task 4: Dashboard API

**Files:**
- Modify: `src/dashboard/app.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_dashboard_api.py`：

```python
import json
import time


@pytest.mark.anyio
async def test_slice_progress_api_returns_idle_when_missing(tmp_path):
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


@pytest.mark.anyio
async def test_slice_progress_api_reads_runtime_file(tmp_path, monkeypatch):
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "slice",
                "phase_label": "切片中",
                "current_slice_percent": 42.5,
                "updated_at": time.time(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))

    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["phase_label"] == "切片中"
    assert response.json()["current_slice_percent"] == 42.5


@pytest.mark.anyio
async def test_slice_progress_api_marks_stale(tmp_path, monkeypatch):
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps({"status": "running", "phase": "slice", "updated_at": time.time() - 600}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))

    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["stale"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_dashboard_api.py::test_slice_progress_api_returns_idle_when_missing -q
```

Expected: `404 Not Found`。

- [ ] **Step 3: 实现 API**

在 `src/dashboard/app.py` 导入：

```python
from src.burn.slice_progress import load_progress_state
```

在 `create_app()` 内加入：

```python
    @app.get("/api/slice-progress")
    async def get_slice_progress() -> Dict[str, Any]:
        return load_progress_state()
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_dashboard_api.py -q
```

Expected: dashboard API 测试通过。

- [ ] **Step 5: 提交**

```powershell
git add src/dashboard/app.py tests/test_dashboard_api.py
git commit -m "feat: expose slice progress api"
```

---

### Task 5: 前端进度显示

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_dashboard_frontend.py`：

```python
FRONTEND_CSS = Path("frontend/styles.css")


def test_frontend_contains_slice_progress_panel():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert 'id="slice-progress-panel"' in text
    assert 'id="slice-progress-bar"' in text
    assert 'id="slice-progress-percent"' in text


def test_frontend_polls_slice_progress_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request("/api/slice-progress")' in text
    assert "renderSliceProgress" in text
    assert "setInterval" in text


def test_frontend_styles_slice_progress_panel():
    text = FRONTEND_CSS.read_text(encoding="utf-8")
    assert ".progress-panel" in text
    assert ".progress-fill" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_dashboard_frontend.py -q
```

Expected: 新增断言失败。

- [ ] **Step 3: 修改 HTML**

在 `frontend/index.html` 中 `div#error` 前加入：

```html
          <section id="slice-progress-panel" class="progress-panel" aria-live="polite">
            <div class="progress-main">
              <div>
                <div id="slice-progress-title" class="progress-title">空闲</div>
                <div id="slice-progress-message" class="progress-message">暂无切片任务</div>
              </div>
              <div class="progress-meta">
                <span id="slice-progress-source">-</span>
                <span id="slice-progress-count">0/0</span>
                <span id="slice-progress-percent">0%</span>
              </div>
            </div>
            <div class="progress-track">
              <div id="slice-progress-bar" class="progress-fill" style="width: 0%"></div>
            </div>
          </section>
```

- [ ] **Step 4: 修改 JS**

在 `elements` 中加入：

```javascript
  progressPanel: document.querySelector("#slice-progress-panel"),
  progressTitle: document.querySelector("#slice-progress-title"),
  progressMessage: document.querySelector("#slice-progress-message"),
  progressSource: document.querySelector("#slice-progress-source"),
  progressCount: document.querySelector("#slice-progress-count"),
  progressPercent: document.querySelector("#slice-progress-percent"),
  progressBar: document.querySelector("#slice-progress-bar"),
```

加入渲染和轮询函数：

```javascript
function renderSliceProgress(progress) {
  const percent = Math.max(0, Math.min(100, Number(progress.current_slice_percent || 0)));
  const status = progress.stale ? "stale" : (progress.status || "idle");
  elements.progressPanel.dataset.status = status;
  elements.progressTitle.textContent = progress.phase_label || "空闲";
  elements.progressMessage.textContent = progress.stale
    ? "进度已停止更新，请检查切片进程"
    : (progress.error || progress.message || "暂无切片任务");
  elements.progressSource.textContent = progress.source_name || "-";
  elements.progressCount.textContent = `${Number(progress.current_slice || 0)}/${Number(progress.total_slices || 0)}`;
  elements.progressPercent.textContent = `${percent.toFixed(0)}%`;
  elements.progressBar.style.width = `${percent}%`;
}

async function refreshSliceProgress() {
  try {
    renderSliceProgress(await request("/api/slice-progress"));
  } catch (error) {
    renderSliceProgress({
      status: "error",
      phase_label: "进度不可用",
      message: error.message,
      current_slice_percent: 0,
    });
  }
}
```

在首次 `refresh();` 后调用：

```javascript
refreshSliceProgress();
```

加入轮询：

```javascript
setInterval(() => {
  if (document.visibilityState === "visible") {
    refreshSliceProgress();
  }
}, 2000);
```

在 `visibilitychange` 中也调用 `refreshSliceProgress()`。

- [ ] **Step 5: 修改 CSS**

追加到 `frontend/styles.css`：

```css
.progress-panel {
  margin: 16px 24px 0;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
}

.progress-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.progress-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.progress-message {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.progress-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 180px;
  justify-content: flex-end;
  font-size: 12px;
  color: var(--text-secondary);
}

.progress-track {
  height: 8px;
  margin-top: 10px;
  overflow: hidden;
  background: #f5f5f5;
  border-radius: var(--radius);
}

.progress-fill {
  height: 100%;
  width: 0%;
  background: var(--primary);
  transition: width 0.2s ease;
}

.progress-panel[data-status="complete"] .progress-fill {
  background: var(--success);
}

.progress-panel[data-status="error"] .progress-fill,
.progress-panel[data-status="stale"] .progress-fill {
  background: var(--danger);
}
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_dashboard_frontend.py -q
```

Expected: frontend 静态测试通过。

- [ ] **Step 7: 提交**

```powershell
git add frontend/index.html frontend/app.js frontend/styles.css tests/test_dashboard_frontend.py
git commit -m "feat: show slice progress on dashboard"
```

---

### Task 6: 全量验证与手工检查

**Files:**
- Modify: `docs/scan.md`

- [ ] **Step 1: 更新文档**

在 `docs/scan.md` 的流程说明中增加一句：

```markdown
切片进度写入 `logs/runtime/slice-progress.json`，Dashboard 通过 `/api/slice-progress` 展示当前流水线阶段和 ffmpeg 片段百分比。该文件位于 SMB/CIFS 项目目录，不写入 Pi SD 卡。
```

- [ ] **Step 2: 运行目标测试**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_slice_progress.py tests/test_slice_context.py tests/test_dashboard_api.py tests/test_dashboard_frontend.py -q
```

Expected: 所有目标测试通过。

- [ ] **Step 3: 运行 dashboard build 脚本**

Run:

```powershell
npm run dashboard:build
```

Expected: 输出 `dashboard frontend is static; no build step`，退出码 0。

- [ ] **Step 4: 检查 diff**

Run:

```powershell
git diff --check
```

Expected: 无 trailing whitespace 或冲突标记。

- [ ] **Step 5: 提交文档和收尾**

```powershell
git add docs/scan.md docs/superpowers/specs/2026-05-22-slice-progress-dashboard-design.md docs/superpowers/plans/2026-05-22-slice-progress-dashboard.md
git commit -m "docs: document slice progress dashboard"
```

---

## 自检

- 规格覆盖：状态文件、后端 API、前端轮询、ffmpeg 百分比、SD 卡写入边界、测试均有任务覆盖。
- 占位检查：计划中没有待填内容；每个代码步骤都包含目标文件和具体片段。
- 类型一致性：`current_slice_percent`、`phase_label`、`stale` 等字段在 writer、API、前端中名称一致。
