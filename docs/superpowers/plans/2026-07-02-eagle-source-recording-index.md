# Eagle Source Recording Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual Eagle plugin sync that mirrors current bilive source recordings as lightweight bookmark cards without copying original videos.

**Architecture:** bilive exposes a read-only Eagle-specific source recording index built from the existing source workbench inventory. The Eagle plugin fetches that index, maps each recording to stable tags/annotation/bookmark metadata, and runs an incremental mirror against Eagle items managed by this plugin.

**Tech Stack:** FastAPI, pytest, static Eagle plugin files, browser JavaScript, Node test runner.

---

### Task 1: Add bilive Eagle source index API

**Files:**
- Create: `src/dashboard/eagle_index.py`
- Modify: `src/dashboard/app.py`
- Test: `tests/test_eagle_source_index.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_eagle_source_index.py` with tests that call `/api/eagle/source-recordings`, assert stable Eagle fields, and confirm deleted source files disappear from the current index.

- [ ] **Step 2: Run the focused API tests**

Run: `python -m pytest tests/test_eagle_source_index.py -q`

Expected: fail because the API route and module do not exist.

- [ ] **Step 3: Implement the index builder and route**

Create `src/dashboard/eagle_index.py` with a small `build_eagle_source_index()` function that wraps `build_source_recording_list()` and formats Eagle-oriented fields. Add `GET /api/eagle/source-recordings` in `src/dashboard/app.py`.

- [ ] **Step 4: Run focused API tests**

Run: `python -m pytest tests/test_eagle_source_index.py -q`

Expected: pass.

### Task 2: Add Eagle plugin sync core

**Files:**
- Create: `eagle-plugin/manifest.json`
- Create: `eagle-plugin/index.html`
- Create: `eagle-plugin/src/sync.js`
- Create: `eagle-plugin/src/app.js`
- Test: `eagle-plugin/tests/sync.test.mjs`

- [ ] **Step 1: Write failing sync-core tests**

Create `eagle-plugin/tests/sync.test.mjs` using Node's built-in test runner. Cover annotation parsing, tag generation, incremental create/update/delete planning, and duplicate prevention.

- [ ] **Step 2: Run sync-core tests**

Run: `node --test eagle-plugin/tests/sync.test.mjs`

Expected: fail because `eagle-plugin/src/sync.js` does not exist.

- [ ] **Step 3: Implement sync core**

Create `eagle-plugin/src/sync.js` exporting pure functions for `recordingKey()`, `annotationForRecording()`, `tagsForRecording()`, `parseManagedAnnotation()`, and `planSync()`.

- [ ] **Step 4: Run sync-core tests**

Run: `node --test eagle-plugin/tests/sync.test.mjs`

Expected: pass.

### Task 3: Add Eagle plugin UI wiring

**Files:**
- Modify: `eagle-plugin/index.html`
- Modify: `eagle-plugin/src/app.js`
- Modify: `eagle-plugin/src/sync.js`
- Test: `eagle-plugin/tests/sync.test.mjs`

- [ ] **Step 1: Add tests for Eagle operation payloads**

Extend `sync.test.mjs` to assert that planned create/update operations include bookmark URL, tags, annotation, and optional base64 thumbnail fields.

- [ ] **Step 2: Run tests**

Run: `node --test eagle-plugin/tests/sync.test.mjs`

Expected: fail until operation payload helpers exist.

- [ ] **Step 3: Implement plugin UI and Eagle API calls**

Implement a small HTML panel with bilive base URL input, sync button, and result log. `app.js` should fetch `/api/eagle/source-recordings`, query Eagle items tagged `bilive` and `原始录播`, then call `eagle.item.addBookmark()`, `item.save()`, or `item.moveToTrash()` according to the plan.

- [ ] **Step 4: Run sync tests again**

Run: `node --test eagle-plugin/tests/sync.test.mjs`

Expected: pass.

### Task 4: Document and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Document the Eagle integration boundary**

Add short documentation explaining that Eagle mirrors current source recordings only, original videos remain in `Videos/`, and deleted originals are removed from Eagle on next manual sync.

- [ ] **Step 2: Run targeted verification**

Run:

```powershell
python -m pytest tests/test_eagle_source_index.py -q
node --test eagle-plugin/tests/sync.test.mjs
python -m compileall src tests
```

Expected: all pass.
