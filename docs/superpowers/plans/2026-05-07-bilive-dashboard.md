# Bilive Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first bilive dashboard that replaces the blrec bundled frontend as the main entry and provides a slice review workbench.

**Architecture:** Keep blrec as a backend recording engine on `127.0.0.1:2234`. Add a bilive FastAPI dashboard on `0.0.0.0:2233`, serving a no-build static frontend and JSON APIs. The first slice page scans local `Videos/`, previews generated slices, and persists human feedback sidecars.

**Tech Stack:** Python FastAPI, pytest, static HTML/JavaScript/CSS.

---

## File Structure

- Create `src/dashboard/__init__.py`: package marker.
- Create `src/dashboard/schemas.py`: dataclasses and response models for rooms, slices, feedback, safe media ids.
- Create `src/dashboard/file_store.py`: scan `Videos/`, map safe ids to paths, read/write feedback JSON.
- Create `src/dashboard/app.py`: FastAPI app, static frontend serving, slice API, blrec proxy placeholder.
- Create `tests/test_dashboard_file_store.py`: scanner and feedback tests.
- Create `frontend/index.html`: app entry.
- Create `frontend/app.js`: dashboard API calls and slice workbench state.
- Create `frontend/styles.css`: dashboard styling.
- Modify root `package.json`: add `dashboard:build` as a static frontend verification placeholder.
- Create `start_dashboard.sh`: starts blrec on `2234` and dashboard on `2233`.
- Modify `record.sh`: make blrec host/port configurable, defaulting to `127.0.0.1:2234` when used by dashboard.

## Task 1: Dashboard File Store

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/schemas.py`
- Create: `src/dashboard/file_store.py`
- Test: `tests/test_dashboard_file_store.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

from src.dashboard.file_store import DashboardFileStore


def test_lists_generated_slices_and_derives_feedback_path(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    source = room / "8792912_20260506-18-56-51.mp4"
    source.write_bytes(b"source")
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    store = DashboardFileStore(videos)
    slices = store.list_slices(room_id="8792912")

    assert len(slices) == 1
    assert slices[0].room_id == "8792912"
    assert slices[0].name == clip.name
    assert slices[0].source_recording.endswith(source.name)
    assert slices[0].feedback_path.endswith("_feedback.json")


def test_feedback_round_trip_is_limited_to_videos_root(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    clip = room / "3100s_8792912_20260506-18-56-51.mp4"
    clip.write_bytes(b"clip")

    store = DashboardFileStore(videos)
    item = store.list_slices("8792912")[0]
    feedback = store.write_feedback(
        item.id,
        {
            "decision": "drop",
            "quality_reason": "不好笑",
            "manual_range": {"start": 0, "end": 130, "relative_to": "slice"},
        },
    )

    assert feedback["decision"] == "drop"
    assert store.read_feedback(item.id)["quality_reason"] == "不好笑"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=. /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_file_store.py -q`

Expected: import failure for `src.dashboard`.

- [ ] **Step 3: Implement minimal file store**

Implement `DashboardFileStore` with:

- safe root resolution under `Videos/`;
- slice detection by filename regex `^\d+(?:\.\d+)?s_.*\.(mp4|flv)$`;
- source recording inference by stripping the `<seconds>s_` prefix;
- feedback sidecar path `<slice_stem>_feedback.json`;
- JSON read/write with `decision` constrained to `keep/drop/review`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=. /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_file_store.py -q`

Expected: `2 passed`.

## Task 2: Dashboard FastAPI Backend

**Files:**
- Create: `src/dashboard/app.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing API tests**

```python
from fastapi.testclient import TestClient

from src.dashboard.app import create_app


def test_slices_api_lists_candidates(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")

    client = TestClient(create_app(videos_root=videos))
    response = client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "3100s_8792912_20260506-18-56-51.mp4"


def test_feedback_api_updates_sidecar(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")
    client = TestClient(create_app(videos_root=videos))
    slice_id = client.get("/api/slices?room_id=8792912").json()[0]["id"]

    response = client.patch(
        f"/api/slices/{slice_id}/feedback",
        json={"decision": "keep", "quality_reason": "值得精切"},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "keep"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=. /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_api.py -q`

Expected: import failure or missing endpoint failure.

- [ ] **Step 3: Implement backend endpoints**

Expose:

- `GET /api/rooms`
- `GET /api/slices`
- `PATCH /api/slices/{slice_id}/feedback`
- `GET /api/media/{media_id}`

Use `DashboardFileStore` for all file access. Do not add upload or delete endpoints in Task 2.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `PYTHONPATH=. /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_api.py tests/test_dashboard_file_store.py -q`

Expected: all pass.

## Task 3: Static Slice Workbench

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/app.js`
- Create: `frontend/styles.css`
- Modify: `package.json`

- [ ] **Step 1: Add frontend shell**

Create a static dashboard page that renders a fixed left nav, top toolbar, and the Slices page as the default view.

- [ ] **Step 2: Implement Slices page**

The page should call `GET /api/slices`, render a dense list, video preview via `/api/media/{media_id}`, metadata panel, decision buttons, reason input, and manual range numeric inputs.

- [ ] **Step 3: Implement save feedback**

`PATCH /api/slices/{id}/feedback` sends `decision`, `quality_reason`, and `manual_range`.

- [ ] **Step 4: Build**

Run: `npm run dashboard:build`

Expected: prints `dashboard frontend is static; no build step`.

## Task 4: Startup Integration

**Files:**
- Create: `start_dashboard.sh`
- Modify: `record.sh`
- Test: shell static checks and manual smoke commands.

- [ ] **Step 1: Make recorder port configurable**

Add:

```bash
host="${BLREC_HOST:-0.0.0.0}"
port="${BLREC_PORT:-2233}"
```

to `record.sh`, preserving current behavior when environment variables are not set.

- [ ] **Step 2: Add dashboard launcher**

`start_dashboard.sh` should:

- validate `RECORD_KEY`;
- stop existing blrec and dashboard processes;
- start blrec with `BLREC_HOST=127.0.0.1 BLREC_PORT=2234`;
- start dashboard backend on `0.0.0.0:2233`;
- print `http://localhost:2233`.

- [ ] **Step 3: Smoke check**

Run:

```bash
bash -n record.sh
bash -n start_dashboard.sh
```

Expected: both commands exit 0.

## Self Review

- Spec coverage: covers dashboard ownership, blrec backend, slice page, feedback JSON, safe defaults.
- Placeholder scan: no TBD/TODO.
- Type consistency: `slice_id`, `media_id`, `manual_range`, `decision`, and feedback sidecar names are consistent across tasks.
