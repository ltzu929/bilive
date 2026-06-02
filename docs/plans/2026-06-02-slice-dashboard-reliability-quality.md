# Slice Dashboard Reliability and Quality Implementation Plan

> **For agentic workers:** This is a roadmap-level implementation plan for the next bilive slicing improvements. When executing any milestone, create a smaller task plan first and use TDD for behavior changes.

**Goal:** Improve the slicing workflow so task state is transparent, recovery is safe, and candidate slice quality is easier to understand and refine.

**Architecture:** Keep the current Pi/Windows boundary: Pi records and serves the lightweight dashboard; Windows runs worker API and heavy slicing/ASR work. Add explicit task state and quality metadata around the existing pending worker instead of replacing the current pipeline.

**Tech Stack:** FastAPI dashboard, static HTML/CSS/JS frontend, JSON marker/state files under `Videos/` and `logs/runtime/`, existing `src.server.watcher`, `src.burn.slice_only`, burst detection, faster-whisper, feedback refinement.

---

## Scope

This plan covers the selected A+B priorities:

- A. 操作稳定性：任务状态透明、worker 状态可见、pending/done 管理、失败恢复、重跑安全。
- B. 切片质量：候选片段解释、burst 参数可调可见、人工反馈效率、精切入口整合、质量评分可追踪。

Explicitly out of scope for this plan:

- 自动发布到 B 站或上传闭环修复。
- 把切片、ASR、字幕烧录迁回 Pi。
- CUDA/GPU 配置改造。
- 大规模替换当前 `slice_only()` 管线。

## Current Baseline

Current production path:

1. Pi `bilive.service` runs `blrec` on port `2233`.
2. Pi `bilive-dashboard.service` serves `/tasks` on port `2234`.
3. Dashboard `POST /api/slice/start` writes `.mp4.pending` markers via `src/dashboard/slice_control.py`.
4. Browser calls local Windows `http://127.0.0.1:2235/api/worker/run-once`.
5. `src.server.worker_control.start_worker_once()` starts `python -m src.server.watcher --once --videos-dir .\Videos`.
6. `src.server.watcher` processes pending markers and calls `src.burn.slice_only.slice_only()`.
7. `slice_only()` writes progress/diagnostics to `logs/runtime/slice-progress.json` and outputs slice artifacts.
8. Dashboard reads `/api/slices`, `/api/slice-progress`, `/api/slice-diagnostics`.

Known gaps:

- `/api/slice-progress` is global, so it cannot clearly explain every queued source.
- `.pending` and `.done` are enough for idempotency, but not enough for user-facing task history.
- Worker status is split between Pi dashboard state and Windows local API state.
- Requeue/retry currently means manual file operations.
- Burst diagnostics exist but are not enough to tune or compare candidate quality.
- `refine_feedback.sh` is useful but disconnected from the dashboard workflow.

## Design Principles

- Keep source recordings by default. Never delete `.mp4/.xml` unless the user explicitly opts in.
- Keep heavy work on Windows. Dashboard may write small marker/state files on the SMB share but must not run ASR or ffmpeg on Pi.
- Prefer explicit task state over inferred state when it affects recovery.
- Every destructive or duplicate-producing action needs a confirmation or a dry-run path.
- User-facing task names should prefer UP name + recording time, with room ID as secondary metadata.
- Quality improvements should explain why a slice was selected, not just assign a score.

---

## Milestone 1: Task Inventory and Status Model

**Objective:** Make the dashboard show all source recordings and their state: ready, pending, running, done, failed, skipped, stale.

**Files:**

- Modify: `src/dashboard/slice_control.py`
- Modify: `src/dashboard/app.py`
- Create: `src/dashboard/task_state.py`
- Modify: `tests/test_slice_control.py`
- Modify: `tests/test_dashboard_api.py`

**Data model:**

Create a normalized task object derived from source recordings and sidecars:

```json
{
  "room_id": "22384516",
  "room_name": "呜米",
  "source_name": "22384516_20260527-12-55-32.mp4",
  "source_rel_path": "22384516/22384516_20260527-12-55-32.mp4",
  "status": "done",
  "pending_path": "22384516/22384516_20260527-12-55-32.mp4.pending",
  "done_path": "22384516/22384516_20260527-12-55-32.mp4.done",
  "has_xml": true,
  "source_size_mb": 5560.9,
  "updated_at": 1780232107,
  "message": "已处理，生成 3 个切片"
}
```

**Task statuses:**

- `recording`: matching `.flv` exists or source file is still changing.
- `ready`: source `.mp4` and `.xml` exist, no `.pending`, no `.done`.
- `pending`: `.mp4.pending` exists and worker is not currently on that source.
- `running`: progress file names this source and status is `running`.
- `done`: `.mp4.done` exists.
- `failed`: a planned failure sidecar exists, or latest progress for this source ended with `error`.
- `skipped`: source exists but lacks `.xml`, below min size, or matches slice-output naming.
- `stale`: pending or running state is older than a configured threshold.

**API shape:**

Add:

```text
GET /api/tasks
GET /api/tasks?room_id=22384516
```

Keep existing APIs stable:

- `GET /api/rooms`
- `GET /api/slices`
- `GET /api/slice-progress`
- `GET /api/slice-diagnostics`
- `POST /api/slice/start`

**Tests:**

- Task inventory returns ready/pending/done/skipped states from a temp `Videos/` tree.
- Existing `.pending` markers are not duplicated.
- Existing `.done` recordings are not queued by `/api/slice/start`.
- Running state is derived from `slice-progress.json` only when the progress source matches the recording.

**Acceptance:**

- Dashboard can list source recordings even before slices exist.
- A source with `.done` is visibly done rather than disappearing into the slice list only.
- Existing `/api/slices` behavior stays unchanged.

---

## Milestone 2: Worker Visibility and Recovery Controls

**Objective:** Make it clear whether Windows worker API is reachable, whether a one-shot worker is running, and what recovery actions are safe.

**Files:**

- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `src/server/worker_control.py`
- Modify: `src/server/watcher.py`
- Modify: `tests/test_worker_api.py`
- Modify: `tests/test_watcher_once.py`
- Modify: `tests/test_dashboard_frontend.py`

**Frontend behavior:**

- Add a compact worker badge near the start button:
  - `PC worker: 未连接`
  - `PC worker: 空闲`
  - `PC worker: 处理中 PID 1234`
  - `PC worker: 上次退出 0`
- Poll `http://127.0.0.1:2235/api/worker/status` from the browser.
- Keep the current local-worker call path. Pi dashboard must not proxy Windows localhost.

**Recovery actions:**

Add dashboard actions in the task list:

- `启动切片`: queue all ready sources, then trigger worker once.
- `重跑`: remove `.done`, write a fresh `.pending`, trigger worker once.
- `取消等待`: remove `.pending` only when worker is not running on that source.
- `标记已处理`: write `.done` without slicing, only for explicitly skipped/manual cases.

**Backend action API:**

Add small, explicit endpoints:

```text
POST /api/tasks/{task_id}/requeue
POST /api/tasks/{task_id}/cancel-pending
POST /api/tasks/{task_id}/mark-done
```

Use encoded relative path as `task_id`, matching existing media ID style.

**Worker state improvement:**

Extend `worker_status()` to include:

```json
{
  "status": "running",
  "pid": 1234,
  "started_at": 1780232107,
  "command": ["python", "-m", "src.server.watcher", "--once", "--videos-dir", "..."],
  "log_path": "logs/runtime/pc-worker-20260602-120000.log"
}
```

**Tests:**

- Worker status reports `started_at`, `command`, `log_path`.
- `start_worker_once()` still returns `already_running` if process is live.
- Requeue refuses invalid task IDs and refuses source paths outside `Videos/`.
- Cancel pending removes only the marker, not the source `.mp4` or `.xml`.
- Frontend contains local worker status polling and recovery button handlers.

**Acceptance:**

- User can answer: "Is the PC worker running?" without opening logs.
- Stuck pending tasks can be cancelled or requeued from UI.
- Recovery actions never delete source recordings.

---

## Milestone 3: Task-Level History Files

**Objective:** Preserve per-source outcome data so progress does not disappear after the global `slice-progress.json` changes.

**Files:**

- Modify: `src/server/watcher.py`
- Modify: `src/burn/slice_only.py`
- Modify: `src/burn/slice_progress.py`
- Create: `src/burn/task_history.py`
- Modify: `tests/test_watcher_once.py`
- Add: `tests/test_task_history.py`

**State files:**

Write a history sidecar next to each source:

```text
Videos/<room>/<source>.mp4.task.json
```

Successful shape:

```json
{
  "source_rel_path": "22384516/22384516_20260527-12-55-32.mp4",
  "status": "done",
  "started_at": "2026-06-02T12:00:00",
  "finished_at": "2026-06-02T12:31:00",
  "worker_pid": 1234,
  "slice_count": 3,
  "output_slices": [
    "22384516/3488s_22384516_20260527-12-55-32.mp4"
  ],
  "diagnostics": [],
  "log_path": "logs/runtime/pc-worker-20260602-120000.log"
}
```

Failed shape:

```json
{
  "source_rel_path": "22384516/22384516_20260527-12-55-32.mp4",
  "status": "failed",
  "started_at": "2026-06-02T12:00:00",
  "finished_at": "2026-06-02T12:02:00",
  "error": "No danmaku file",
  "diagnostics": []
}
```

**Rules:**

- `.done` still means successfully processed.
- `.task.json` is user-facing history and may exist for done, failed, skipped, or cancelled tasks.
- A failed task keeps or recreates `.pending` only if it is safe to retry automatically. Default: remove pending and mark failed, requiring explicit requeue.

**Tests:**

- `watcher --once` writes task history on success.
- Failed processing writes `status=failed` and error text.
- Dashboard task inventory uses `.task.json` message when present.
- Existing `.done` behavior remains compatible.

**Acceptance:**

- Refreshing the dashboard after a run still shows what happened to each source.
- Failed sources have explicit messages and a requeue path.

---

## Milestone 4: Quality Explanation Panel

**Objective:** Turn current diagnostics into actionable slice-quality explanations.

**Files:**

- Modify: `src/autoslice/burst_detector.py`
- Modify: `src/autoslice/danmaku_slice.py`
- Modify: `src/burn/slice_only.py`
- Modify: `src/dashboard/file_store.py`
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `tests/test_autoslice.py`
- Modify: `tests/test_dashboard_api.py`
- Modify: `tests/test_dashboard_frontend.py`

**Backend metadata:**

Persist a compact quality summary per generated slice, preferably in existing feedback or analysis sidecars:

```json
{
  "source_recording": "...",
  "density_core": {"start": 3488.0, "end": 3498.0},
  "context_window": {"start": 3428.0, "end": 3548.0},
  "burst": {
    "ratio": 6.5,
    "danmaku_count": 8813,
    "baseline_density": 1.0,
    "local_density": 6.5,
    "rank": 1
  },
  "analysis": {
    "quality_score": 0.74,
    "quality_reason": "弹幕密度高，音频情绪较强",
    "retain_recommendation": true
  }
}
```

**Dashboard display:**

For selected slice, show:

- 爆点排名。
- 峰值倍率。
- 弹幕数。
- 上下文窗口。
- ASR/音频质量原因。
- 标题/保留建议来源：heuristic / LM judge / qwen-omni / fallback。

**Tests:**

- Burst detector returns enough data to explain selected events.
- Slice item API includes `quality_score`, `quality_reason`, `burst_ratio`, `burst_rank` when sidecars exist.
- Frontend renders quality fields without overlapping preview controls.

**Acceptance:**

- User can tell why a candidate appears in the list.
- A bad candidate can be traced to weak burst data, weak ASR, or failed judge rather than guessed.

---

## Milestone 5: Burst Parameter Tuning

**Objective:** Let the user tune candidate generation safely without editing TOML for every experiment.

**Files:**

- Modify: `src/dashboard/slice_control.py`
- Modify: `src/server/watcher.py`
- Modify: `src/burn/slice_only.py`
- Modify: `src/autoslice/danmaku_slice.py`
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `tests/test_slice_control.py`
- Modify: `tests/test_watcher_once.py`

**UI controls:**

Add an "高级参数" collapsed panel:

- `burst_ratio`: default from config, range 1.5 to 8.0.
- `burst_context`: default from config, choices 30s / 45s / 60s / 90s.
- `burst_top_n`: default from config, range 1 to 5.
- `min_video_size`: default from config, read-only at first.

**Marker extension:**

Allow pending markers to carry per-run options:

```json
{
  "video_rel_path": "22384516/22384516_20260527-12-55-32.mp4",
  "room_id": "22384516",
  "action": "slice",
  "created_by": "dashboard",
  "slice_options": {
    "burst_ratio": 3.0,
    "burst_context": 60,
    "burst_top_n": 3
  }
}
```

**Rules:**

- Missing `slice_options` keeps current config behavior.
- Invalid `slice_options` are rejected by `/api/slice/start`.
- Done/requeue preserves the options chosen for that run in `.task.json`.

**Tests:**

- `/api/slice/start` writes `slice_options` when provided.
- Invalid burst ratio returns HTTP 400.
- `watcher` passes marker options into `slice_only()`.
- Existing markers without options still work.

**Acceptance:**

- User can run a second pass with a lower/higher burst threshold without editing config.
- The task history records which parameters produced the candidates.

---

## Milestone 6: Review Workflow Speed

**Objective:** Make manual keep/drop/review faster and more reliable.

**Files:**

- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `src/dashboard/file_store.py`
- Modify: `tests/test_dashboard_api.py`
- Modify: `tests/test_dashboard_frontend.py`

**Features:**

- Add filter chips for `review`, `keep`, `drop`, `refined`, `queued`.
- Add keyboard shortcuts:
  - `K`: keep
  - `D`: drop
  - `R`: review
  - `J`: next candidate
  - `L`: replay current preview
- Add "未处理优先" sort.
- Keep current plain static frontend; no framework migration.

**Feedback sidecar extension:**

Extend existing `_feedback.json`:

```json
{
  "decision": "keep",
  "quality_reason": "开场反应强，有可用标题",
  "manual_range": {"start": 4.0, "end": 58.0, "relative_to": "slice"},
  "reviewed_at": "2026-06-02T12:40:00",
  "review_source": "dashboard"
}
```

**Tests:**

- Feedback API persists `reviewed_at` and `review_source`.
- Frontend contains keyboard handler and does not trigger shortcuts while typing in textarea/input.
- Filters keep selection stable after save.

**Acceptance:**

- Reviewing 20 candidates does not require repeated mouse movement.
- Existing feedback files remain readable.

---

## Milestone 7: Dashboard-Controlled Refinement Dry Run

**Objective:** Bring `refine_feedback.sh` into the dashboard without automatically uploading or publishing.

**Files:**

- Modify: `src/burn/feedback_refine.py`
- Modify: `src/dashboard/app.py`
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `tests/test_dashboard_api.py`
- Modify: `tests/test_feedback_refine.py`

**API:**

Add dry-run first:

```text
POST /api/refine/preview
POST /api/refine/run
```

Dry-run output:

```json
{
  "keep_count": 3,
  "review_count": 12,
  "drop_count": 5,
  "would_generate": [
    {
      "feedback_path": "..._feedback.json",
      "source_slice": "...mp4",
      "range": {"start": 4.0, "end": 58.0},
      "reason": "manual_range"
    }
  ]
}
```

Run behavior:

- Generate refined clips for `keep`.
- Update feedback sidecars with `refined=true`.
- Default to `--no-upload-queue` from the dashboard until upload workflow is separately approved.

**Tests:**

- Dry-run does not write files.
- Run writes refined clips and feedback metadata.
- Dashboard run defaults to no upload queue.

**Acceptance:**

- User can see exactly what refinement will do before running it.
- No upload queue insertion happens from dashboard unless a later plan explicitly enables it.

---

## Milestone 8: Cleanup and Guardrails

**Objective:** Reduce confusion from legacy entrypoints and prevent accidental old-scan usage.

**Files:**

- Modify: `README.md`
- Modify: `docs/project-health.md`
- Modify: `docs/scan.md`
- Move or document: `_slice_daemon.bat`, `_test_slice.bat`, `agent.sh`
- Modify: `start_pipeline.ps1`
- Modify: `server.sh`

**Actions:**

- Add `scripts/legacy/` and move old shortcuts only after confirming no desktop shortcuts depend on their path.
- Add a startup warning if `src.burn.scan_slice` is run without `--once`.
- Keep `start_pipeline.ps1 -RunLegacyScanSlice` as compatibility for one release, then remove in a later cleanup.
- Document the new dashboard task/recovery model.

**Tests/checks:**

- `python -m pytest tests/test_dashboard_api.py tests/test_dashboard_frontend.py tests/test_slice_control.py tests/test_watcher_once.py`
- `python -m compileall src/dashboard src/server src/burn`
- `git diff --check`
- `ssh pi "bash -n /mnt/win/bilive/slice.sh"`

**Acceptance:**

- Daily workflow docs point to one primary path.
- Legacy paths are visibly marked and cannot be confused with the current pending worker.

---

## Suggested Execution Order

1. Milestone 1: Task Inventory and Status Model.
2. Milestone 2: Worker Visibility and Recovery Controls.
3. Milestone 3: Task-Level History Files.
4. Milestone 4: Quality Explanation Panel.
5. Milestone 6: Review Workflow Speed.
6. Milestone 5: Burst Parameter Tuning.
7. Milestone 7: Dashboard-Controlled Refinement Dry Run.
8. Milestone 8: Cleanup and Guardrails.

Reasoning:

- Status transparency must come before recovery controls.
- Task history must come before richer quality explanations, otherwise explanations disappear after refresh.
- Review workflow speed can improve daily use before deeper burst tuning.
- Refinement should wait until review and quality metadata are stable.
- Cleanup is safer after the new path is documented and working.

## Verification Strategy

Run focused tests per milestone, then this dashboard core set:

```powershell
cd D:\alldata\pi\bilive
python -m pytest tests/test_dashboard_api.py tests/test_dashboard_frontend.py tests/test_slice_control.py tests/test_watcher_once.py tests/test_worker_api.py
python -m compileall src/dashboard src/server src/burn
git diff --check
```

Manual verification after UI milestones:

1. Open `http://192.168.31.157:2234/tasks`.
2. Confirm room dropdown shows UP names.
3. Confirm source task list shows ready/pending/done states.
4. Start PC worker API with `.\start_pc_worker_api.ps1`.
5. Click start slice and confirm worker status changes.
6. Confirm a completed source gets `.done` and `.task.json`.
7. Confirm requeue requires explicit action and does not delete source files.

## Risks

| Risk | Mitigation |
|------|------------|
| Dashboard scans too many large files | Limit metadata reads, derive task state from filenames/sidecars, avoid reading media bytes. |
| Browser cannot reach Windows worker API | Keep visible "未连接" state and keep manual `start_pc_worker_api.ps1` instructions. |
| Requeue causes duplicate slices | Preserve task history, show existing generated slices, require confirmation for done sources. |
| Quality metadata schema drifts | Store versioned sidecar keys and keep missing fields optional. |
| Upload queue gets touched accidentally | Keep dashboard refinement default as dry-run/no-upload-queue. |

## Open Decisions

These should be decided before implementation:

1. Stale pending threshold: 30 minutes, 60 minutes, or user-configurable?
2. Should dashboard "重跑" delete old generated slices, hide them, or keep them and mark the new run separately?
3. Should burst tuning apply to all ready sources at once or only selected sources?
4. Should task history live beside source files (`Videos/<room>/*.task.json`) or under `logs/runtime/tasks/`?
5. Should dashboard refinement ever enqueue upload candidates, or should upload remain CLI-only until a separate upload plan?
