# Dashboard Navigation and Media Playback Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard navigation honest and make MP4/FLV preview playback reliable without regressing the existing MP4 media path.

**Architecture:** Keep the slice dashboard as the only custom page on port 2233. Treat blrec on port 2234 as an external recorder console, and link to it only where the target is proven. Keep original media serving for browser-native MP4, and add an explicit FLV preview path that prepares a cached MP4 only when needed.

**Tech Stack:** FastAPI, Starlette `FileResponse`, static HTML/CSS/JS, ffmpeg copy remux for FLV preview, pytest/httpx ASGI tests.

---

## Evidence From Diagnosis

- Current 2233 process is `python -m uvicorn src.dashboard.app:api --host 0.0.0.0 --port 2233` with cwd `/home/zk/projects/bilive/.worktrees/slice-edit-instructions`.
- `GET /api/media/<3100s mp4 id>` returns `200 OK` with `Content-Type: video/mp4`.
- `GET /api/preview/<3100s mp4 id>` returns `404 Not Found` in the currently running backend.
- `GET /api/media/<3130s flv id>` returns `200 OK` with `Content-Type: video/x-flv`, which Chrome cannot play in `<video>`.
- `GET /api/preview/<3130s flv id>` returns `404 Not Found` in the currently running backend.
- Current served HTML has `任务` and `录播` both pointing to `http://127.0.0.1:2234/tasks`; `http://127.0.0.1:2234/tasks` and `/settings` both redirect to `/`, so those are not reliable distinct page routes.

## File Structure

- Modify `frontend/index.html`: replace misleading hard-coded navigation links with verified links and disabled states.
- Modify `frontend/styles.css`: style disabled nav items and keep link/button nav visually consistent.
- Modify `frontend/app.js`: choose `/api/media` for `.mp4`, choose `/api/preview` only for `.flv`, and show media load errors.
- Modify `src/dashboard/app.py`: keep `/api/media/{media_id}` stable, add `/api/preview/{media_id}` for FLV preview only, return clear errors when preview preparation fails.
- Modify `src/dashboard/file_store.py`: expose `resolve_preview_media()` and cache FLV remux outputs under `Videos/.dashboard-cache/previews`.
- Modify `tests/test_dashboard_api.py`: cover MP4 direct media, FLV preview, and route behavior.
- Add `tests/test_dashboard_frontend.py`: static assertions for navigation targets and media URL selection.

---

### Task 1: Restore MP4 Playback to the Stable Media Path

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Write the failing frontend static test**

Create `tests/test_dashboard_frontend.py` with:

```python
from pathlib import Path


FRONTEND_JS = Path("frontend/app.js")


def test_mp4_media_uses_original_media_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "item.name.toLowerCase().endsWith(\".flv\")" in text
    assert "return `/api/media/${encodeURIComponent(item.media_id)}`;" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=/home/zk/projects/bilive/.worktrees/slice-edit-instructions /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_frontend.py::test_mp4_media_uses_original_media_endpoint -q
```

Expected: FAIL because `frontend/app.js` currently always returns `/api/preview/...`.

- [ ] **Step 3: Write minimal implementation**

Change `frontend/app.js`:

```javascript
function mediaUrl(item) {
  if (item.name.toLowerCase().endsWith(".flv")) {
    return `/api/preview/${encodeURIComponent(item.media_id)}`;
  }
  return `/api/media/${encodeURIComponent(item.media_id)}`;
}
```

Change `renderDetails()`:

```javascript
elements.previewVideo.src = mediaUrl(item);
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.

Expected: PASS.

---

### Task 2: Add FLV Preview Route Without Replacing `/api/media`

**Files:**
- Modify: `src/dashboard/app.py`
- Modify: `src/dashboard/file_store.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_dashboard_api.py`:

```python
@pytest.mark.anyio
async def test_media_api_serves_mp4_source(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"mp4")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/media/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_preview_api_remuxes_flv_to_cached_mp4(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    flv_path = room / "3130s_8792912_20260506-18-56-51.flv"
    flv_path.write_bytes(b"flv")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        command[-1].write_bytes(b"mp4-preview")

    monkeypatch.setattr("src.dashboard.file_store.subprocess.run", fake_run)
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/preview/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4-preview"
    assert response.headers["content-type"].startswith("video/mp4")
    assert commands[0][:4] == ["ffmpeg", "-y", "-i", flv_path]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
env PYTHONPATH=/home/zk/projects/bilive/.worktrees/slice-edit-instructions /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_api.py::test_media_api_serves_mp4_source tests/test_dashboard_api.py::test_preview_api_remuxes_flv_to_cached_mp4 -q
```

Expected: preview test fails if `/api/preview` is not implemented.

- [ ] **Step 3: Implement FLV preview only**

In `src/dashboard/file_store.py`, add:

```python
import subprocess
```

Add method:

```python
def resolve_preview_media(self, media_id: str) -> Path:
    path = self.resolve_media(media_id)
    if path.suffix.lower() != ".flv":
        return path
    return self._ensure_mp4_preview(path)
```

Add helper:

```python
def _ensure_mp4_preview(self, path: Path) -> Path:
    relative = path.relative_to(self.videos_root).as_posix()
    cache_name = base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii")
    cache_root = self.videos_root / ".dashboard-cache" / "previews"
    output_path = cache_root / f"{cache_name}.mp4"

    if output_path.is_file() and output_path.stat().st_mtime >= path.stat().st_mtime:
        return output_path

    cache_root.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-c", "copy", "-movflags", "+faststart", temp_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        temp_path.replace(output_path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError("Unable to prepare preview media") from exc
    return output_path
```

In `src/dashboard/app.py`, add:

```python
@app.get("/api/preview/{media_id}")
async def get_preview(media_id: str) -> FileResponse:
    try:
        path = store.resolve_preview_media(media_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="video/mp4")
```

- [ ] **Step 4: Run tests to verify pass**

Run the same pytest command.

Expected: PASS.

---

### Task 3: Make Navigation Honest and Non-Misleading

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Test: `tests/test_dashboard_frontend.py`

- [ ] **Step 1: Write failing navigation test**

Add to `tests/test_dashboard_frontend.py`:

```python
from pathlib import Path


FRONTEND_HTML = Path("frontend/index.html")


def test_navigation_does_not_map_multiple_items_to_blrec_tasks():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert text.count('href="http://127.0.0.1:2234/tasks"') <= 1
    assert 'href="/tasks"' in text
    assert 'aria-disabled="true"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
env PYTHONPATH=/home/zk/projects/bilive/.worktrees/slice-edit-instructions /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_frontend.py::test_navigation_does_not_map_multiple_items_to_blrec_tasks -q
```

Expected: FAIL because current HTML maps both `任务` and `录播` to `http://127.0.0.1:2234/tasks`.

- [ ] **Step 3: Replace misleading nav**

Use this navigation in `frontend/index.html`:

```html
<nav>
  <a class="nav-item" href="http://127.0.0.1:2234/">录播控制台</a>
  <a class="nav-item active" href="/tasks">切片</a>
  <span class="nav-item disabled" aria-disabled="true">上传</span>
  <span class="nav-item disabled" aria-disabled="true">设置</span>
</nav>
```

Append to `frontend/styles.css`:

```css
.nav-item.disabled {
  color: #9aa6b2;
  cursor: not-allowed;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.

Expected: PASS.

---

### Task 4: Verify Running Server After Restart

**Files:**
- No code edits.

- [ ] **Step 1: Restart dashboard**

Run:

```bash
cd /home/zk/projects/bilive/.worktrees/slice-edit-instructions
./start_dashboard.sh
```

Expected: output includes `Dashboard: http://127.0.0.1:2233/tasks`.

- [ ] **Step 2: Verify MP4 endpoint**

Run with the actual MP4 id from `/api/slices`:

```bash
curl -s -D - -o /tmp/bilive-media-mp4.bin -r 0-1023 'http://127.0.0.1:2233/api/media/<mp4-media-id>'
```

Expected: `HTTP/1.1 200 OK` or `HTTP/1.1 206 Partial Content`, `Content-Type: video/mp4`.

- [ ] **Step 3: Verify FLV preview endpoint**

Run with the actual FLV id from `/api/slices`:

```bash
curl -s -D - -o /tmp/bilive-preview-flv.bin -r 0-1023 'http://127.0.0.1:2233/api/preview/<flv-media-id>'
```

Expected: `HTTP/1.1 200 OK` or `HTTP/1.1 206 Partial Content`, `Content-Type: video/mp4`, and a new file under `Videos/.dashboard-cache/previews/`.

- [ ] **Step 4: Browser smoke test**

Open:

```text
http://127.0.0.1:2233/tasks
```

Expected:
- MP4 row plays.
- FLV row prepares preview and plays after ffmpeg finishes.
- Left navigation has one external recorder-console link and no misleading duplicate `tasks` links.

---

## Final Verification

Run:

```bash
env PYTHONPATH=/home/zk/projects/bilive/.worktrees/slice-edit-instructions /home/zk/projects/bilive/venv/bin/python -m pytest tests/test_dashboard_file_store.py tests/test_dashboard_api.py tests/test_dashboard_frontend.py tests/test_edit_instruction.py tests/test_slice_context.py tests/test_autoslice.py::TestAnalysisResult tests/test_autoslice.py::TestSliceQualityFilter -q
bash -n record.sh start_dashboard.sh
git diff --check
npm run dashboard:build
```

Expected:
- All pytest tests pass.
- Shell syntax check exits 0.
- `git diff --check` exits 0.
- `npm run dashboard:build` exits 0.
