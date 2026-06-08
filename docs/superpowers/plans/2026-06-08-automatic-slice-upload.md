# Automatic Slice Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically upload retained slices and submit them to Bilibili from the recommended Windows PC worker, with resumable two-phase publishing and bounded retries.

**Architecture:** Keep SQLite as the queue authority, migrate legacy rows into an explicit state machine, and split UPOS transfer from Web archive submission so a failed submission never uploads the bytes again. A long-running upload worker is managed by the existing PC worker API and protected by a process lock.

**Tech Stack:** Python 3.13, SQLite, requests, FastAPI, PowerShell, pytest

---

## File Structure

- Modify `src/db/conn.py`: schema migration, queue repository, transactional claims, state transitions, recovery, and compatibility wrappers.
- Modify `src/upload/bilitool/bilitool/upload/bili_upload.py`: Web `add/v3` submission request for an already uploaded remote filename.
- Modify `src/upload/bilitool/bilitool/controller/upload_controller.py`: expose separate transfer and submission operations.
- Rewrite `src/upload/upload.py`: testable resumable worker, cookie loading, bounded retries, lock, and status file.
- Create `src/server/upload_control.py`: upload subprocess lifecycle and status reader.
- Modify `src/server/worker_api.py`: lifespan auto-start and upload status/start endpoints.
- Modify `src/config/server_config.py`: upload runtime settings.
- Modify `bilive-server.toml`: default automatic upload configuration.
- Modify `start_pipeline.ps1`: delegate upload process ownership to worker API.
- Modify `start_pc_worker_api.ps1`: document and preserve automatic startup.
- Modify `run_upload.ps1`: retain explicit manual consumer entry point.
- Modify `sync_cookie.py`: remove obsolete client endpoint warning.
- Modify `README.md`, `AGENTS.md`, `docs/upload.md`, `docs/known-issues.md`, `docs/project-health.md`: current operating model and recovery notes.
- Create `tests/test_upload_queue.py`: migration and state machine tests.
- Create `tests/test_bilibili_web_submit.py`: Web submission request tests.
- Create `tests/test_upload_worker.py`: two-phase processing, retry, cleanup, auth, lock, and status tests.
- Create `tests/test_upload_control.py`: subprocess lifecycle tests.
- Modify `tests/test_worker_api.py`: lifespan and upload API tests.
- Modify `tests/test_pc_launcher.py`: PowerShell ownership and disable-switch tests.

### Task 1: Upload Queue Schema And State Machine

**Files:**
- Modify: `src/db/conn.py`
- Create: `tests/test_upload_queue.py`

- [ ] **Step 1: Write failing legacy migration tests**

Create a temporary legacy database with only `id`, `video_path`, and `locked`.
Assert that `migrate_upload_queue()` adds the new columns and maps rows:

```python
def test_migrate_upload_queue_preserves_locked_rows_as_failed(tmp_path):
    db_path = tmp_path / "data.db"
    create_legacy_queue(db_path, [("queued.mp4", 0), ("locked.mp4", 1)])

    migrate_upload_queue(db_path)

    rows = list_upload_queue(db_path)
    assert rows[0]["status"] == "queued"
    assert rows[1]["status"] == "failed"
    assert rows[1]["locked"] == 1
```

- [ ] **Step 2: Run the migration test and verify RED**

Run:

```powershell
python -m pytest tests/test_upload_queue.py::test_migrate_upload_queue_preserves_locked_rows_as_failed -v
```

Expected: FAIL because `migrate_upload_queue` and the new row fields do not exist.

- [ ] **Step 3: Implement idempotent schema migration**

Add `connect(db_path=None)`, `migrate_upload_queue(db_path=None)`, row factories,
column inspection, and explicit migration defaults. Migration must be safe to
run at every process startup and must never turn `locked != 0` into active work.

- [ ] **Step 4: Write failing claim and transition tests**

Cover:

```python
item = claim_next_upload(db_path, now=100)
assert item["status"] == "uploading"

mark_upload_complete(item["video_path"], "remote-name", db_path=db_path, now=101)
assert get_upload_item(item["video_path"], db_path)["status"] == "uploaded"

claimed = claim_next_upload(db_path, now=102)
assert claimed["status"] == "publishing"
```

Also cover `schedule_upload_retry`, `mark_upload_published`,
`mark_upload_failed`, `recover_upload_queue`, and `get_upload_queue_counts`.

- [ ] **Step 5: Run state tests and verify RED**

Run:

```powershell
python -m pytest tests/test_upload_queue.py -v
```

Expected: FAIL on missing repository operations.

- [ ] **Step 6: Implement transactional queue operations**

Use `BEGIN IMMEDIATE` for claim operations. Select only due `queued` and
`uploaded` rows ordered by `id`. Transition `queued` to `uploading`, and
`uploaded` to `publishing`. Persist `remote_filename` before submission.
Recover stale `uploading` to `queued` and stale `publishing` to `uploaded`.

Keep the existing public helpers (`insert_upload_queue`,
`get_all_upload_queue`, `delete_upload_queue`, and lock helpers) compatible
with callers and diagnostics.

- [ ] **Step 7: Run queue tests and compatibility tests**

Run:

```powershell
python -m pytest tests/test_upload_queue.py tests/test_slice_only_model_unload.py tests/test_feedback_refine.py tests/test_source_workbench.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit queue state machine**

```powershell
git add src/db/conn.py tests/test_upload_queue.py
git commit -m "feat: add resumable upload queue states"
```

### Task 2: Current Web Submission API

**Files:**
- Modify: `src/upload/bilitool/bilitool/upload/bili_upload.py`
- Modify: `src/upload/bilitool/bilitool/controller/upload_controller.py`
- Create: `tests/test_bilibili_web_submit.py`

- [ ] **Step 1: Write a failing Web submission request test**

Inject a fake session and assert:

```python
response = uploader.publish_video("remote-filename")

assert request.url.startswith("https://member.bilibili.com/x/vu/web/add/v3")
assert request.params["csrf"] == "csrf-token"
assert request.json["videos"] == [{
    "filename": "remote-filename",
    "title": "clip title",
    "desc": "clip description",
}]
```

The test response returns `{"code": 0, "data": {"bvid": "BV1test"}}`, and the
method must return the response data without performing another UPOS upload.

- [ ] **Step 2: Run the Web submission test and verify RED**

Run:

```powershell
python -m pytest tests/test_bilibili_web_submit.py -v
```

Expected: FAIL because the current code posts form data to `/x/vu/client/add`.

- [ ] **Step 3: Implement Web `add/v3` submission**

Use the configured authenticated session. Send JSON with query parameters
`t=<milliseconds>` and `csrf=<bili_jct>`. Return the complete response mapping
so callers can distinguish authentication, retryable, and permanent errors.

- [ ] **Step 4: Split transfer from submit in UploadController**

Expose:

```python
def upload_video_file(self, video_path, cdn=None) -> str: ...
def submit_uploaded_video(self, remote_filename) -> dict: ...
```

Do not make `submit_uploaded_video` call `upload_video_file`.

- [ ] **Step 5: Run submission and package tests**

Run:

```powershell
python -m pytest tests/test_bilibili_web_submit.py tests/test_upload_package_imports.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit submission API**

```powershell
git add src/upload/bilitool/bilitool/upload/bili_upload.py src/upload/bilitool/bilitool/controller/upload_controller.py tests/test_bilibili_web_submit.py
git commit -m "fix: submit uploads through bilibili web api"
```

### Task 3: Resumable Upload Worker

**Files:**
- Rewrite: `src/upload/upload.py`
- Modify: `src/config/server_config.py`
- Modify: `bilive-server.toml`
- Create: `tests/test_upload_worker.py`

- [ ] **Step 1: Write failing two-phase success test**

Use a temporary queue and fake client:

```python
result = worker.process_one(now=100)

assert client.upload_calls == [str(video_path)]
assert client.submit_calls == ["remote-file"]
assert result.status == "published"
assert result.bvid == "BV1test"
```

Assert the DB records `published`, `remote_filename`, and `bvid`, and configured
cleanup removes the video and `.upload.json`.

- [ ] **Step 2: Run success test and verify RED**

Run:

```powershell
python -m pytest tests/test_upload_worker.py::test_process_one_uploads_and_publishes_slice -v
```

Expected: FAIL because the current module is an infinite procedural loop.

- [ ] **Step 3: Implement Worker result and one-item processing**

Add `UploadSettings`, `UploadResult`, `BilibiliUploadClient`, and
`UploadWorker.process_one(now=None)`. Validate local file and metadata before
network access. Persist the remote filename immediately after UPOS completion.

- [ ] **Step 4: Write failing publish-resume test**

The fake client uploads once, fails the first publish, then succeeds:

```python
first = worker.process_one(now=100)
second = worker.process_one(now=200)

assert client.upload_calls == [str(video_path)]
assert client.submit_calls == ["remote-file", "remote-file"]
assert second.status == "published"
```

- [ ] **Step 5: Implement bounded retry scheduling**

Classify network errors and nonzero API responses. Increment attempts once per
failed item processing, schedule `next_attempt_at` with exponential backoff,
and mark terminal `failed` after `max_attempts`. Preserve
`remote_filename` for publish retries.

- [ ] **Step 6: Write and implement auth pause tests**

Assert invalid credentials are detected before `claim_next_upload`, later rows
remain untouched, status reports `paused_auth`, and `auth_retry_seconds`
controls the next validation.

- [ ] **Step 7: Write and implement validation and cleanup tests**

Cover missing files, malformed sidecars, cleanup disabled, cover cleanup, and
success status output. Sanitize errors so cookie values cannot enter SQLite or
the status file.

- [ ] **Step 8: Write and implement process-lock tests**

The first `UploadProcessLock` acquisition succeeds; a second acquisition of the
same path raises `UploadAlreadyRunning`. Releasing the first lock permits a
new acquisition.

- [ ] **Step 9: Implement run loop and CLI**

`run_forever()` migrates and recovers once, writes status atomically, processes
due items, sleeps for the configured poll interval, and handles SIGINT/SIGTERM.
`main()` resolves project paths and returns zero for an already-running
consumer. Add these explicit modes:

```text
python -m src.upload.upload --status
python -m src.upload.upload --check-auth
python -m src.upload.upload --once
```

`--status` migrates and reports queue state without claiming work.
`--check-auth` validates the configured cookie without claiming work.
`--once` processes at most one item and exits.

- [ ] **Step 10: Run all worker tests**

Run:

```powershell
python -m pytest tests/test_upload_worker.py -v
```

Expected: PASS with no external requests.

- [ ] **Step 11: Commit upload worker**

```powershell
git add src/upload/upload.py src/config/server_config.py bilive-server.toml tests/test_upload_worker.py
git commit -m "feat: add resumable automatic upload worker"
```

### Task 4: Upload Process Control And Worker API

**Files:**
- Create: `src/server/upload_control.py`
- Create: `tests/test_upload_control.py`
- Modify: `src/server/worker_api.py`
- Modify: `tests/test_worker_api.py`

- [ ] **Step 1: Write failing process controller tests**

Assert `start_upload_worker()` spawns:

```text
python -m src.upload.upload
```

with project, config, videos, DB, cookie, and status paths in the environment.
Assert duplicate starts return `already_running`.

- [ ] **Step 2: Run controller tests and verify RED**

Run:

```powershell
python -m pytest tests/test_upload_control.py -v
```

Expected: FAIL because `src.server.upload_control` does not exist.

- [ ] **Step 3: Implement process controller**

Mirror `worker_control` lifecycle patterns. Add `upload_worker_status()` that
combines process state with `upload-status.json`. Add
`stop_upload_worker()` that only terminates the child started by this process.

- [ ] **Step 4: Write failing worker API lifespan and endpoint tests**

Use injected starter/status/stopper callables. Assert:

- app lifespan starts upload once when enabled;
- disabled mode does not start;
- `GET /api/upload/status` returns status;
- `POST /api/upload/start` starts or reports an error;
- lifespan shutdown invokes the stopper.

- [ ] **Step 5: Implement FastAPI upload lifecycle**

Use an async lifespan context manager. Preserve existing worker endpoints and
CORS behavior. Resolve automatic startup from config plus
`BILIVE_AUTO_UPLOAD`.

- [ ] **Step 6: Run server tests**

Run:

```powershell
python -m pytest tests/test_upload_control.py tests/test_worker_api.py tests/test_worker_control.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit process lifecycle**

```powershell
git add src/server/upload_control.py src/server/worker_api.py tests/test_upload_control.py tests/test_worker_api.py
git commit -m "feat: manage uploader from pc worker api"
```

### Task 5: Windows Launchers And Documentation

**Files:**
- Modify: `start_pipeline.ps1`
- Modify: `start_pc_worker_api.ps1`
- Modify: `run_upload.ps1`
- Modify: `sync_cookie.py`
- Modify: `tests/test_pc_launcher.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/upload.md`
- Modify: `docs/known-issues.md`
- Modify: `docs/project-health.md`

- [ ] **Step 1: Write failing launcher ownership tests**

Assert:

```python
assert '"-m", "src.upload.upload"' not in pipeline_text
assert 'BILIVE_AUTO_UPLOAD = "0"' in no_upload_branch
assert "src.server.worker_api:api" in pipeline_text
assert "BILIVE_COOKIE_FILE" in worker_api_text
```

Also assert `run_upload.ps1` remains a direct manual entry point.

- [ ] **Step 2: Run launcher tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pc_launcher.py -v
```

Expected: FAIL because `start_pipeline.ps1` still starts a second upload
consumer.

- [ ] **Step 3: Update PowerShell launchers**

Set common paths, including:

```powershell
$env:BILIVE_DB_PATH = "$ProjectDir\src\db\data.db"
$env:BILIVE_COOKIE_FILE = "$ProjectDir\.secrets\bilibili.cookie"
```

`start_pipeline.ps1 -NoUpload` sets `BILIVE_AUTO_UPLOAD=0` before starting the
worker API. Default mode lets the API own the uploader. `run_upload.ps1`
continues to start the consumer manually and relies on the lock for safety.

- [ ] **Step 4: Update operating documentation**

Remove the obsolete `client/add` known issue and explain current Web
submission, status endpoint, logs, bounded retry, historical failed rows, and
disable switches. State clearly that Pi still only records.

- [ ] **Step 5: Run launcher tests and documentation scans**

Run:

```powershell
python -m pytest tests/test_pc_launcher.py -v
rg -n "client/add|无限重试|单独启动上传" README.md AGENTS.md docs sync_cookie.py
```

Expected: tests PASS; remaining matches, if any, are explicitly marked as
historical rather than current behavior.

- [ ] **Step 6: Commit launchers and docs**

```powershell
git add start_pipeline.ps1 start_pc_worker_api.ps1 run_upload.ps1 sync_cookie.py tests/test_pc_launcher.py README.md AGENTS.md docs/upload.md docs/known-issues.md docs/project-health.md
git commit -m "docs: enable automatic slice upload workflow"
```

### Task 6: Offline Regression And Production Verification

**Files:**
- Modify only if failures reveal defects in files already listed.

- [ ] **Step 1: Run focused upload suite**

Run:

```powershell
python -m pytest tests/test_upload_queue.py tests/test_bilibili_web_submit.py tests/test_upload_worker.py tests/test_upload_control.py tests/test_worker_api.py tests/test_pc_launcher.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full offline suite**

Run:

```powershell
python -m pytest
```

Expected: PASS with integration tests excluded by `pytest.ini`.

- [ ] **Step 3: Run static checks**

Run:

```powershell
python -m compileall src
git diff --check
git status --short
```

Expected: compilation succeeds, no whitespace errors, and only intended
changes remain.

- [ ] **Step 4: Inspect production queue without mutation**

Run:

```powershell
python -m src.upload.upload --status
```

Expected: schema is migrated; counts and eligible file names are printed
without claiming or uploading; historical locked rows remain `failed`.

- [ ] **Step 5: Validate the real cookie without claiming work**

Run:

```powershell
python -m src.upload.upload --check-auth
```

Expected: logged-in account information is returned and no queue state changes.

- [ ] **Step 6: Start one-item production verification**

Run:

```powershell
python -m src.upload.upload --once
```

Expected: one currently eligible slice reaches `published`, returns a BVID,
and the DB records one `remote_filename`.

- [ ] **Step 7: Verify no duplicate transfer**

Inspect the status, queue row, and log for the verified item. Confirm exactly
one UPOS transfer and one successful Web submission. Confirm no historical
failed row was reactivated.

- [ ] **Step 8: Run final regression after production verification**

Run:

```powershell
python -m pytest
git status --short
```

Expected: PASS and clean worktree.
