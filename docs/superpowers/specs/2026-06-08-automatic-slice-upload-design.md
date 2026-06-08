# Automatic Slice Upload Design

## Goal

When the Windows PC worker is running, every slice retained by the automatic
LLM quality decision is uploaded and submitted to Bilibili without requiring a
separate upload command.

The same consumer continues to handle refined clips that a user explicitly
marks `keep` in the source workbench. Automatic upload can be disabled for
local slicing tests.

## Current State

- `src.burn.slice_only` already writes `<slice>.upload.json` and inserts the
  slice path into SQLite `upload_queue`.
- `src.upload.upload` consumes that queue only when a separate process is
  started.
- The uploader sends video bytes to Bilibili successfully, then submits with
  the obsolete `/x/vu/client/add` endpoint. Current logs show that endpoint
  returning `code=-101`.
- A failed publish currently causes the same video bytes to be uploaded again.
- Rows with `locked=1` are retried forever by the current consumer.
- `start_pc_worker_api.ps1` is the recommended PC entry point but does not
  start the upload consumer.

## Decisions

### Automatic publication boundary

The default mode is automatic publication of slices retained by the existing
LLM quality decision. A slice rejected by the quality decision is deleted and
never queued. A `judge_failed` slice remains available for manual review and is
not queued automatically.

Refined clips created from an explicit workbench `keep` decision remain
eligible for the same upload queue.

### Submission API

Keep the existing UPOS/CDN upload implementation, but replace the obsolete
client submission request with the current Web submission endpoint:

```text
POST https://member.bilibili.com/x/vu/web/add/v3?t=<milliseconds>&csrf=<bili_jct>
Content-Type: application/json
```

The JSON body contains the archive metadata and a `videos` array whose first
entry contains the remote filename returned by the completed UPOS upload.
Submission success requires `code == 0` and records the returned `bvid`.

### Credential source

`.secrets/bilibili.cookie` is the runtime source of truth. The uploader parses
the semicolon-delimited cookie file directly and requires at least `SESSDATA`
and `bili_jct`. It builds a fresh `requests.Session` from those cookies and
validates the session against `/x/web-interface/nav` before claiming a queue
item.

`cookie.json` and the vendored bilitool `config.json` are retained for backward
compatibility, but automatic upload does not depend on synchronizing them.
Secrets are never written to logs or SQLite.

## Queue State Machine

SQLite remains the authoritative queue. Startup performs an idempotent schema
migration that adds these columns to `upload_queue`:

| Column | Purpose |
| --- | --- |
| `status` | `queued`, `uploading`, `uploaded`, `publishing`, `published`, or `failed` |
| `remote_filename` | UPOS filename persisted before archive submission |
| `attempts` | Number of failed processing attempts |
| `next_attempt_at` | Earliest Unix timestamp for another attempt |
| `last_error` | Sanitized most recent failure |
| `bvid` | Bilibili BV identifier after successful submission |
| `updated_at` | Last state transition time |

Existing rows migrate as follows:

- `locked=0` becomes `queued`.
- `locked=1` or `locked=2` becomes `failed` and is not automatically retried.

The legacy `locked` column remains populated for compatibility: active states
use `locked=0`, and terminal `failed` rows use `locked=1`.

State transitions are:

```text
queued -> uploading -> uploaded -> publishing -> published
   |          |            |            |
   +----------+------------+------------+-> retry or failed
```

The remote filename is committed in the `uploaded` transition before the Web
submission request starts. If submission fails or the process exits, the next
attempt starts from `uploaded` and only repeats submission. It never sends the
video bytes again.

On consumer startup, a stale `uploading` row returns to `queued`. A stale
`publishing` row returns to `uploaded` when `remote_filename` is present.

## Consumer Behavior

The consumer processes one item at a time:

1. Acquire a process lock under `logs/runtime/` so only one consumer can run.
2. Migrate and recover the queue state.
3. Validate the cookie without claiming an item.
4. Atomically claim the oldest due `queued` or `uploaded` item.
5. Upload bytes only when no `remote_filename` is stored.
6. Submit the archive through Web `add/v3`.
7. On success, record `published` and `bvid`, then delete the local slice,
   upload metadata sidecar, generated cover, and any transient upload state.
8. Poll for the next due item.

Network and server failures use bounded exponential backoff. The defaults are
three attempts with delays of 30, 60, and 120 seconds. After the third failure,
the row becomes `failed` and processing continues with later queue items.

Authentication failures do not claim new items. If a publish request returns
an authentication or CSRF error, the current item keeps its remote filename,
returns to `uploaded`, and follows the same bounded retry policy. The consumer
writes a paused authentication status until the cookie validates again.

Missing local files become `failed` without contacting Bilibili. A malformed
metadata sidecar becomes `failed` before upload.

## Automatic Startup

The PC worker API owns the upload consumer lifecycle:

- A new upload process controller starts `python -m src.upload.upload` during
  the FastAPI lifespan.
- It exposes `GET /api/upload/status` and `POST /api/upload/start` for
  diagnostics and manual recovery.
- The child writes `logs/runtime/upload-status.json` with state, current path,
  queue counts, last error, and last successful `bvid`.
- The process lock prevents duplicates when another launcher or recovery
  request races with startup.
- Worker API shutdown terminates the child it started.

`start_pc_worker_api.ps1` enables automatic upload by default.
`start_pipeline.ps1` delegates upload startup to the worker API instead of
starting a second consumer.

`BILIVE_AUTO_UPLOAD=0` or `start_pipeline.ps1 -NoUpload` disables automatic
startup while preserving manual `run_upload.ps1` operation.

The following configuration is added to `bilive-server.toml`:

```toml
[upload]
auto_start = true
poll_interval_seconds = 10
max_attempts = 3
retry_base_seconds = 30
auth_retry_seconds = 120
delete_after_success = true
```

Environment variable `BILIVE_AUTO_UPLOAD` overrides `auto_start`.

## Components

### Queue repository

`src/db/conn.py` owns schema migration, transactional claiming, transitions,
retry scheduling, recovery, and queue counts. Higher-level upload code does
not issue SQL.

### Bilibili client

The vendored upload controller remains responsible for UPOS transfer. Its
public operations are separated into:

- upload a local file and return the remote filename;
- submit a previously uploaded remote filename and return the BVID.

The Web submission implementation accepts an injected session in tests.

### Upload worker

`src/upload/upload.py` becomes a testable worker with `process_one()` and
`run_forever()` entry points. Queue state changes occur around each external
operation, and broad retry decorators no longer wrap both UPOS upload and
submission.

### Process control

`src/server/upload_control.py` mirrors the existing slice worker control but
manages the long-running upload process and reads its status file.

## Testing

All automated tests use temporary SQLite databases, temporary video files, and
fake Bilibili clients. They make no external requests and never publish.

Required coverage:

- schema migration preserves old rows and does not reactivate locked rows;
- an unlocked legacy row becomes `queued`;
- a queue item transitions through upload and publish exactly once;
- a failed publish persists `remote_filename`, and restart only republishes;
- retryable failures stop after the configured limit;
- authentication failure does not claim later items;
- missing files and malformed metadata fail before network access;
- successful publication records the BVID and performs configured cleanup;
- stale in-progress states recover to the correct phase;
- the process lock rejects a second consumer;
- worker API lifespan auto-starts one consumer;
- `BILIVE_AUTO_UPLOAD=0` and `-NoUpload` suppress automatic startup;
- upload status endpoints report idle, running, paused, and failed states.

The existing fast offline suite remains required.

## Deployment And Existing Queue

Deployment does not unlock the existing `locked=1` rows. They represent prior
failed uploads and may include duplicate remote CDN objects.

The currently unlocked rows are eligible for automatic processing the next
time the PC worker API starts with automatic upload enabled. Before that first
production run:

1. validate `.secrets/bilibili.cookie`;
2. run a dry status check showing the exact eligible queue count;
3. start the consumer;
4. verify one real item reaches `published` and returns a BVID;
5. confirm the same item was uploaded to UPOS only once.

## Out Of Scope

- Automatically retrying or unlocking historical failed rows.
- A new dashboard upload management page.
- Uploading source recordings that were not generated or approved as clips.
- Running upload, slicing, ASR, or rendering on the Raspberry Pi.
- Changing the existing LLM retention decision.

## Acceptance Criteria

The feature is complete when:

1. A retained slice is queued without manual upload commands.
2. Starting the recommended PC worker API starts exactly one upload consumer.
3. A queued slice is uploaded and submitted through Web `add/v3`.
4. A publish failure after UPOS upload cannot cause the bytes to be uploaded
   again.
5. Failures are bounded, visible, and do not create an infinite retry loop.
6. Historical locked rows remain untouched.
7. Automatic upload can be disabled for local testing.
8. Offline tests pass and one authorized production slice returns a real BVID.
