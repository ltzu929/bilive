# Modern Slice Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the bilive slicing page around the supplied modern dashboard reference while preserving every production data binding and the real danmaku density chart.

**Architecture:** Keep the existing static HTML/CSS/JavaScript frontend and Dashboard API contracts. Reorganize existing DOM nodes into an overview plus three-column review workspace, then add small render helpers only where the new presentation needs derived labels or status classes.

**Tech Stack:** Static HTML, CSS, browser JavaScript, pytest contract tests, FastAPI static serving.

---

### Task 1: Lock the new DOM contract

**Files:**
- Modify: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Add a failing layout contract test**

Assert that the HTML contains the new `studio-topbar`, `overview-card`,
`review-workspace`, `density-card`, and `review-summary` structures while still
containing `density-chart` and `density-segment-layer`.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/test_dashboard_frontend.py -q`

Expected: failure because the modern layout selectors do not exist yet.

### Task 2: Rebuild the page structure and visual system

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`

- [ ] **Step 1: Reorganize existing bound elements**

Keep every ID consumed by `frontend/app.js`, but move them into the modern
sidebar, topbar, overview, queue, preview, density, review, diagnostics, and
task sections.

- [ ] **Step 2: Replace legacy styling with reference-aligned tokens**

Implement the reference palette, 76px navigation, 76px header, 16px cards,
overview grid, three-column workspace, queue states, video card, density card,
review form, responsive breakpoints, and accessible focus states.

- [ ] **Step 3: Run the focused contract tests**

Run: `python -m pytest tests/test_dashboard_frontend.py -q`

Expected: all frontend contract tests pass.

### Task 3: Bind presentation-specific state

**Files:**
- Modify: `frontend/app.js`
- Modify: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Add failing assertions for status presentation**

Assert that source rows render structured status badges and that overview
diagnostic stages receive semantic state classes.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/test_dashboard_frontend.py -q`

Expected: failure until the render helpers exist.

- [ ] **Step 3: Add minimal render helpers**

Derive localized source status labels, selected recording metadata, selected
segment status classes, and diagnostic stage classes without changing API
requests or action behavior.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_dashboard_frontend.py -q`

Expected: pass.

### Task 4: Verify behavior and visual fidelity

**Files:**
- Create: `design-qa.md`
- Create: `artifacts/modern-slice-dashboard.png`

- [ ] **Step 1: Run automated verification**

Run:

```powershell
python -m pytest -q
python -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

Expected: all commands pass with no broken requirements.

- [ ] **Step 2: Start the local Dashboard**

Run the existing Dashboard application on an unused localhost port with the
project configuration and open `/tasks`.

- [ ] **Step 3: Capture and compare**

Capture a 1920x1080 implementation screenshot, compare it with the supplied
reference image, fix all P0/P1/P2 layout or interaction differences, and save
the final report to `design-qa.md` with `final result: passed`.

