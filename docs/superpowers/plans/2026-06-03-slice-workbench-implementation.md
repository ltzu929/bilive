# Slice Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement fail-closed LLM judging and replace the lower `/tasks` dashboard with a source-recording workbench driven by source history, density data, and segment status.

**Architecture:** Keep the existing pending-marker and watcher architecture. Add durable segment metadata to the existing `.mp4.task.json` sidecar, expose a focused dashboard read model from `src/dashboard/source_workbench.py`, and reuse the existing static frontend with new workbench rendering functions.

**Tech Stack:** Python 3, FastAPI, pytest/httpx, plain HTML/CSS/JavaScript, existing SMB-backed `Videos` sidecars.

---

## File Structure

- Modify `src/autoslice/analysis_result.py`: add `judge_status`, `judge_error`, and source-window fields to `AnalysisResult`.
- Modify `src/autoslice/mllm_sdk/judge.py`: make fallback judge results fail closed with `judge_status="judge_failed"`.
- Modify `src/burn/slice_only.py`: record per-candidate segments, retain `judge_failed` files without upload, and return `segments` in the pipeline result.
- Modify `src/burn/task_history.py`: persist `segments` in `.mp4.task.json`.
- Create `src/dashboard/source_workbench.py`: build the source list/detail API payloads, compute 10-second density points from XML, and perform manual keep/drop sidecar mutations.
- Modify `src/dashboard/app.py`: add source workbench and segment action endpoints.
- Modify `frontend/index.html`: replace the old lower workbench markup with source list, source preview/density chart, and permanent manual panel; make task queue collapsible.
- Modify `frontend/app.js`: fetch and render source recordings, render SVG area chart overlays, seek/pause source video, and call segment action APIs.
- Modify `frontend/styles.css`: style collapsible queue, source list, area chart, overlays, and right panel.
- Tests:
  - `tests/test_local_llm_judge.py`
  - `tests/test_slice_only_model_unload.py`
  - `tests/test_task_history.py`
  - `tests/test_source_workbench.py`
  - `tests/test_dashboard_api.py`
  - `tests/test_dashboard_frontend.py`

## Task 1: Judge Result Fail-Closed Model

**Files:**
- Modify: `src/autoslice/analysis_result.py`
- Modify: `src/autoslice/mllm_sdk/judge.py`
- Test: `tests/test_local_llm_judge.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting:

```python
def test_local_subprocess_missing_command_is_judge_failed():
    result = judge.judge_and_title_local_subprocess([], artist="artist")
    assert result.retain is False
    assert result.judge_status == "judge_failed"
    assert "not configured" in result.judge_error
```

and for JSON parse failure:

```python
def test_local_subprocess_bad_json_is_judge_failed(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "not json"
        stderr = ""
    monkeypatch.setattr(judge.subprocess, "run", lambda *args, **kwargs: Completed())
    result = judge.judge_and_title_local_subprocess(["python"], artist="artist")
    assert result.retain is False
    assert result.judge_status == "judge_failed"
    assert "JSON parse failed" in result.judge_error
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_local_llm_judge.py -q
```

Expected: fail because `JudgeResult` has no `judge_status` and fallback currently keeps by default.

- [ ] **Step 3: Implement minimal model changes**

Add fields to `JudgeResult`:

```python
judge_status: str = "keep"
judge_error: str = ""
```

Add fields to `AnalysisResult` and include them in `from_dict()` and `to_dict()`:

```python
judge_status: str = "keep"
judge_error: str = ""
```

Update `JudgeResult.to_analysis_result()` to pass those fields through.

Change `_fallback_result()` to:

```python
return JudgeResult(
    retain=False,
    retain_reason=reason,
    title=f"{artist}精彩片段",
    description="精彩直播片段",
    content_type="other",
    quality_score=0.0,
    judge_status="judge_failed",
    judge_error=reason,
)
```

Set parsed results to `judge_status="keep"` when `retain=True` and `judge_status="drop"` when `retain=False`.

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python -m pytest tests/test_local_llm_judge.py -q
```

Expected: all tests pass.

## Task 2: Slice Pipeline Segment Recording

**Files:**
- Modify: `src/burn/slice_only.py`
- Modify: `src/burn/task_history.py`
- Test: `tests/test_slice_only_model_unload.py`
- Test: `tests/test_task_history.py`

- [ ] **Step 1: Write failing tests**

Add a test where `generate_title()` returns:

```python
AnalysisResult(
    title="fallback",
    description="desc",
    retain_recommendation=False,
    quality_reason="LLM failed: 502",
    judge_status="judge_failed",
    judge_error="LLM failed: 502",
)
```

Assert:

```python
result = slice_only_module.slice_only(str(source))
assert result["slice_count"] == 0
assert result["judge_failed_count"] == 1
assert slice_path.exists()
assert queued == []
assert result["segments"][0]["judge_status"] == "judge_failed"
assert result["segments"][0]["candidate_rel_path"].endswith(slice_path.name)
```

Add a task history test:

```python
path = write_task_history(source, status="done", videos_root=videos, segments=[{"judge_status": "judge_failed"}])
data = json.loads(path.read_text(encoding="utf-8"))
assert data["segments"][0]["judge_status"] == "judge_failed"
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_slice_only_model_unload.py tests/test_task_history.py -q
```

Expected: fail because `segments` are not returned or persisted.

- [ ] **Step 3: Implement segment collection**

In `slice_only()`, initialize:

```python
segments = []
judge_failed_count = 0
```

For every generated candidate, append a segment with:

```python
{
    "segment_id": stable_segment_id(original_video_path, generated_slice.context_start, generated_slice.context_end),
    "source_rel_path": "",
    "candidate_path": slice_path,
    "candidate_rel_path": "",
    "start_seconds": generated_slice.context_start,
    "end_seconds": generated_slice.context_end,
    "density_core_start": generated_slice.density_core_start,
    "density_core_end": generated_slice.density_core_end,
    "danmaku_count": generated_slice.danmaku_count,
    "judge_status": "...",
    "judge_error": "...",
    "quality_score": result.quality_score,
    "quality_reason": result.quality_reason,
    "title": result.title,
    "description": result.description,
    "tags": result.tags,
    "upload_status": "queued" or "not_queued",
    "manual_override": False,
}
```

When `judge_status == "judge_failed"`, keep the candidate file, increment `judge_failed_count`, append the segment, skip subtitle burn, metadata write, and upload queue insertion.

When `retain_recommendation=False` with `judge_status != "judge_failed"`, mark `drop` and remove the candidate as the current code does.

Return:

```python
{
    "status": "done",
    "slice_count": len(output_slices),
    "judge_failed_count": judge_failed_count,
    "output_slices": output_slices,
    "segments": segments,
    "diagnostics": diagnostics,
}
```

Do not treat "all candidates judge_failed" as pipeline failure.

- [ ] **Step 4: Persist segments**

Add `segments: Optional[List[Dict[str, Any]]] = None` to `write_task_history()`, and write `history["segments"] = segments` when provided.

Update `src/server/watcher.py` to pass `segments=pipeline_result.get("segments")`.

- [ ] **Step 5: Verify tests pass**

Run:

```bash
python -m pytest tests/test_slice_only_model_unload.py tests/test_task_history.py -q
```

Expected: all tests pass.

## Task 3: Source Workbench Read Model And API

**Files:**
- Create: `src/dashboard/source_workbench.py`
- Modify: `src/dashboard/app.py`
- Test: `tests/test_source_workbench.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing read-model tests**

Create tests for:

```python
def test_source_recording_detail_returns_density_and_segments(tmp_path):
    # create Videos/22384516/source.mp4, source.xml, source.mp4.task.json
    detail = build_source_recording_detail(videos, task_id)
    assert detail["density_points"]
    assert detail["segments"][0]["judge_status"] == "judge_failed"
```

and:

```python
def test_source_recording_list_counts_keep_and_judge_failed(tmp_path):
    items = build_source_recording_list(videos)
    assert items[0]["summary_counts"]["keep"] == 1
    assert items[0]["summary_counts"]["judge_failed"] == 1
```

- [ ] **Step 2: Write failing API tests**

Add tests for:

```python
GET /api/source-recordings
GET /api/source-recordings/{task_id}
```

Expected fields: `summary_counts`, `density_points`, `segments`.

- [ ] **Step 3: Verify tests fail**

Run:

```bash
python -m pytest tests/test_source_workbench.py tests/test_dashboard_api.py -q -k "source_recording"
```

Expected: fail because module/endpoints do not exist.

- [ ] **Step 4: Implement `source_workbench.py`**

Implement:

```python
build_source_recording_list(videos_root: str | Path, room_names: dict[str, str] | None = None) -> list[dict]
build_source_recording_detail(videos_root: str | Path, task_id: str, room_names: dict[str, str] | None = None) -> dict
```

Use `task_state.build_task_inventory()` for source discovery and `task_state.resolve_task_id()` for path resolution.

Compute density from source XML with 10-second windows:

```python
start = int(timestamp // 10) * 10
```

Return normalized density as `count / max_count` with `0.0` for empty data.

- [ ] **Step 5: Add endpoints**

In `create_app()` add:

```python
@app.get("/api/source-recordings")
async def list_source_recordings(room_id: str | None = None) -> list[dict]:
    ...

@app.get("/api/source-recordings/{task_id}")
async def get_source_recording(task_id: str) -> dict:
    ...
```

- [ ] **Step 6: Verify tests pass**

Run:

```bash
python -m pytest tests/test_source_workbench.py tests/test_dashboard_api.py -q -k "source_recording"
```

Expected: all selected tests pass.

## Task 4: Segment Manual Actions

**Files:**
- Modify: `src/dashboard/source_workbench.py`
- Modify: `src/dashboard/app.py`
- Test: `tests/test_source_workbench.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing manual action tests**

Add tests that call:

```python
POST /api/segments/{segment_id}/manual-keep
POST /api/segments/{segment_id}/drop
POST /api/segments/{segment_id}/range
POST /api/segments/{segment_id}/retry-judge
POST /api/segments/{segment_id}/render
```

Use a `.task.json` with one `judge_failed` segment. Assert manual keep sets:

```python
judge_status == "manual_keep"
manual_override is True
upload_status == "queued"
```

For this iteration, mock `insert_upload_queue` so no real DB side effect is required.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_source_workbench.py tests/test_dashboard_api.py -q -k "segment"
```

- [ ] **Step 3: Implement sidecar mutation helpers**

Implement helpers to find a segment by `segment_id`, update the task history JSON atomically, and return the updated segment.

Manual keep should accept optional `title`, `description`, `tags`, `start_seconds`, `end_seconds`. If not provided, keep fallback metadata already in the segment.

Drop should set `judge_status="drop"` and `upload_status="not_queued"`.

Range should update `start_seconds` and `end_seconds` only.

Retry judge should resolve the candidate clip, extract danmaku text for the selected source range, call `generate_title()`, and update the segment to `keep`, `drop`, or `judge_failed` based on the returned `AnalysisResult`.

Render should use the current source range to regenerate the candidate clip path and update `candidate_path` / `candidate_rel_path`.

- [ ] **Step 4: Add API endpoints**

Add:

```python
@app.post("/api/segments/{segment_id}/manual-keep")
@app.post("/api/segments/{segment_id}/drop")
@app.post("/api/segments/{segment_id}/range")
@app.post("/api/segments/{segment_id}/retry-judge")
@app.post("/api/segments/{segment_id}/render")
```

Return `400` for invalid payloads and `404` for unknown segment ids.

- [ ] **Step 5: Verify tests pass**

Run:

```bash
python -m pytest tests/test_source_workbench.py tests/test_dashboard_api.py -q -k "segment"
```

## Task 5: Frontend Workbench Structure

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Write failing static frontend tests**

Assert:

```python
assert 'id="source-recording-list"' in html
assert 'id="source-preview-video"' in html
assert 'id="density-chart"' in html
assert 'id="segment-panel"' in html
assert "refreshSourceRecordings" in js
assert "renderDensityChart" in js
assert ".density-area" in css
assert ".segment-overlay-keep" in css
assert ".segment-overlay-judge-failed" in css
```

Also assert task queue collapse controls:

```python
assert 'id="task-toggle"' in html
assert "toggleTaskPanel" in js
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python -m pytest tests/test_dashboard_frontend.py -q
```

- [ ] **Step 3: Update HTML**

Replace the lower old slice-list workbench with:

```html
<div class="workbench source-workbench">
  <section class="panel source-list-panel">...</section>
  <section class="panel source-preview-panel">...</section>
  <section class="panel segment-panel">...</section>
</div>
```

Keep the old `status-filter` only if it still has a useful role; otherwise leave it harmless.

Make task queue header include:

```html
<button id="task-toggle" type="button" aria-expanded="true">折叠</button>
```

- [ ] **Step 4: Update JS**

Add state:

```javascript
sourceRecordings: [],
selectedSourceId: "",
selectedSegmentId: "",
sourceDetail: null,
taskPanelCollapsed: false,
```

Add functions:

```javascript
refreshSourceRecordings()
renderSourceRecordings()
selectSourceRecording(taskId)
refreshSourceDetail(taskId)
renderDensityChart(detail)
selectSegment(segmentId)
renderSegmentPanel()
toggleTaskPanel()
```

Clicking a segment overlay should:

```javascript
sourcePreviewVideo.currentTime = segment.start_seconds || 0;
sourcePreviewVideo.pause();
selectSegment(segment.segment_id);
```

- [ ] **Step 5: Update CSS**

Add source workbench three-column layout, source rows, SVG density area, blue keep overlays, red dashed judge-failed overlays, and right panel controls.

- [ ] **Step 6: Verify static tests pass**

Run:

```bash
python -m pytest tests/test_dashboard_frontend.py -q
```

## Task 6: Full Verification And Service Refresh

**Files:**
- Any files changed above.

- [ ] **Step 1: Run focused backend tests**

```bash
python -m pytest tests/test_local_llm_judge.py tests/test_slice_only_model_unload.py tests/test_task_history.py tests/test_source_workbench.py tests/test_dashboard_api.py -q
```

- [ ] **Step 2: Run frontend tests**

```bash
python -m pytest tests/test_dashboard_frontend.py -q
```

- [ ] **Step 3: Run syntax/format checks**

```bash
python -m compileall src/dashboard src/autoslice src/burn
git diff --check
```

- [ ] **Step 4: Restart dashboard**

```bash
ssh pi "sudo systemctl restart bilive-dashboard && systemctl is-active bilive-dashboard"
```

- [ ] **Step 5: Smoke API**

```bash
ssh pi "curl -s http://127.0.0.1:2234/api/source-recordings | head -c 500"
ssh pi "curl -s http://127.0.0.1:2234/tasks | grep -E 'app.js\\?v=|styles.css\\?v='"
```

Expected: dashboard active, new API returns JSON, `/tasks` references bumped static assets.

## Self-Review

- Spec coverage: fail-closed judge, durable `judge_failed`, source list/detail API, retry judge, manual keep/drop/range/render actions, area chart overlays, and collapsible task queue are covered.
- Type consistency: use `judge_status`, `judge_error`, `segment_id`, `density_points`, `segments`, and `summary_counts` consistently.
- Scope control: GPU ASR, alternate burst algorithms, upload workflow redesign, SSE/WebSocket streaming, and full editor timeline behavior remain out of scope.
