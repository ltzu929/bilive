# Evidence-Driven Slice Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the supported Windows pipeline publish only candidates backed by timestamped ASR, window-specific danmaku, an explicit LLM keep decision, and successful subtitle burning.

**Architecture:** Add a focused candidate analyzer between burst slicing and finalization. Keep `slice_only` as the orchestrator, make queue insertion the final commit point, and remove reachable legacy scan/render entry points.

**Tech Stack:** Python 3.13, pytest, faster-whisper, OpenAI-compatible chat API, ffmpeg, SQLite, FastAPI, PowerShell.

---

### Task 1: Add the candidate analysis contract

**Files:**
- Create: `src/autoslice/candidate_analyzer.py`
- Create: `tests/test_candidate_analyzer.py`

- [ ] Write failing tests proving transcript text, timestamped segments, and danmaku are passed to `judge_and_title`.
- [ ] Write failing tests proving empty transcript or empty valid segments returns `judge_failed` without calling the LLM.
- [ ] Implement `analyze_candidate(video_path, artist, danmaku_text)` using existing `analyze_audio` and `judge_and_title`.
- [ ] Copy valid ASR transcript and segments into the returned `AnalysisResult`.
- [ ] Add `unload_candidate_models()` using existing ASR/emotion cleanup functions.
- [ ] Run `python -m pytest tests/test_candidate_analyzer.py -q`.

### Task 2: Enforce the strict publish gate in `slice_only`

**Files:**
- Modify: `src/burn/slice_only.py`
- Modify: `tests/test_slice_only_model_unload.py`

- [ ] Replace `generate_title` with `analyze_candidate`.
- [ ] Add failing tests for ASR/LLM `judge_failed`, LLM `drop`, subtitle burn failure, queue insertion failure, and successful keep.
- [ ] Keep review candidates on disk without sidecar or queue row.
- [ ] Delete LLM-dropped candidate files.
- [ ] Require successful subtitle burning before writing upload metadata.
- [ ] Mark a segment `queued` only when SQLite insertion returns true.
- [ ] Return accurate `slice_count`, `output_slices`, and segment `upload_status`.
- [ ] Run `python -m pytest tests/test_slice_only_model_unload.py tests/test_slice_upload_metadata.py -q`.

### Task 3: Reuse the same analyzer for dashboard judge retry

**Files:**
- Modify: `src/dashboard/source_workbench.py`
- Modify: `tests/test_source_workbench.py`

- [ ] Change judge retry to call `analyze_candidate`.
- [ ] Add tests proving retry preserves `judge_failed` on ASR/LLM failure and never queues implicitly.
- [ ] Keep `manual_keep` as the only human override that bypasses automatic LLM keep.
- [ ] Run `python -m pytest tests/test_source_workbench.py tests/test_dashboard_api.py -q`.

### Task 4: Remove reachable legacy processing paths

**Files:**
- Modify: `src/server/watcher.py`
- Modify: `start_pipeline.ps1`
- Delete: `src/burn/scan_slice.py`
- Delete: `tests/test_scan_slice.py`
- Modify: `tests/test_watcher_once.py`
- Modify: `tests/test_pc_launcher.py`

- [ ] Add a failing watcher test proving `action=render` is rejected.
- [ ] Remove the watcher render branch.
- [ ] Remove `-RunLegacyScanSlice`, `-NoSlice`, and scan process startup from `start_pipeline.ps1`.
- [ ] Delete the full-directory scan module and its tests.
- [ ] Add launcher assertions that `src.burn.scan_slice` is absent.
- [ ] Run `python -m pytest tests/test_watcher_once.py tests/test_pc_launcher.py -q`.

### Task 5: Align configuration and documentation

**Files:**
- Modify: `bilive-server.toml`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/scan.md`
- Modify: `docs/project-health.md`
- Modify: `docs/known-issues.md`
- Modify: `docs/asr-engines.md`

- [ ] Document the single production path and strict automatic-publish gate.
- [ ] Remove instructions for legacy full-directory scanning.
- [ ] Stop presenting title-only model providers or heuristic quality scoring as supported production decisions.
- [ ] Document review behavior for ASR, LLM, subtitle, metadata, and queue failures.
- [ ] Search for stale terms with `rg -n "RunLegacyScanSlice|src\\.burn\\.scan_slice|启发式.*评分|qwen-omni" README.md AGENTS.md docs start_pipeline.ps1`.

### Task 6: Add an offline pipeline contract test

**Files:**
- Create: `tests/test_evidence_pipeline.py`

- [ ] Build a temporary recording, XML, generated candidate, upload sidecar, and temporary SQLite database.
- [ ] Verify a keep result plus successful subtitle burn inserts exactly one queued row.
- [ ] Verify a second processing attempt cannot insert a duplicate queue row.
- [ ] Verify a review result creates no upload sidecar and no queue row.
- [ ] Run `python -m pytest tests/test_evidence_pipeline.py -q`.

### Task 7: Full verification and Git delivery

**Files:**
- Modify only files required by failed verification.

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall src -q`.
- [ ] Run `git diff --check`.
- [ ] Inspect `git diff --stat` and `git status --short`.
- [ ] Commit the pipeline optimization on `feat/automatic-slice-upload`.
- [ ] Merge the feature branch into `main`.
- [ ] Re-run `python -m pytest -q` on merged `main`.
- [ ] Remove the owned `.worktrees/automatic-slice-upload` worktree and delete the merged feature branch.
- [ ] Update root `D:\alldata\pi\AGENTS.md` so operational guidance matches the merged implementation.
