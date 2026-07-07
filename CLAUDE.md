# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Bilive is a self-maintained Bilibili live recording, slice-analysis, subtitle, and upload pipeline. It is split across two nodes with a strict execution boundary:

- **Pi** — runs blrec recording (`0.0.0.0:2233`), the dashboard (`0.0.0.0:2234`), and an SMB-recovery timer. Pi **never** runs ffmpeg, faster-whisper, MiMo, subtitle burning, or uploads.
- **Windows** — runs the heavy Worker API (`127.0.0.1:2235`, on-demand, auto-exits after 15 min idle) and all processing. Started remotely from the Pi dashboard over SSH, or locally via `start_pipeline.ps1`.
- **Cloud** — Xiaomi MiMo `mimo-v2.5` does multi-modal judgment + rough-cut suggestions on candidate videos.

The Python entry points and data flow live in [docs/architecture.md](docs/architecture.md); the operational boundary constraints (do not move processing onto Pi, cross-process locks, etc.) live in [AGENTS.md](AGENTS.md) — both are authoritative and must be respected when changing code.

## Commands

Windows heavy env is `.venv-win\Scripts\python.exe` (created by `setup_windows_env.ps1`). `venv/` and `.venv-win/` are both gitignored local envs.

```powershell
# Test (default excludes @pytest.mark.integration — those need real keys/media/SDKs)
.\.venv-win\Scripts\python.exe -m pytest -q
.\.venv-win\Scripts\python.exe -m pytest tests/test_pipeline_stages.py -q          # single file
.\.venv-win\Scripts\python.exe -m pytest tests/test_pipeline_stages.py::test_name -q
.\.venv-win\Scripts\python.exe -m pytest -m integration -q                         # opt into integration

# Byte-compile + dependency sanity
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check

# Eagle plugin (Node test runner; plain JS, no build step)
node --test eagle-plugin\tests\sync.test.mjs

# Launch the Windows Worker API manually (production launcher; worker_server is the real entry)
.\start_pipeline.ps1
.\start_pipeline.ps1 -NoUpload                    # disable the upload consumer

# Confirm upload auth before enabling uploads
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
```

Deploy/PS1/shell changes require PowerShell parse + `bash -n` + systemd unit validation on top of the above (per [AGENTS.md](AGENTS.md)).

## Configuration & secrets

Two TOML files, both **gitignored** and not committed:

- `settings.toml` — blrec recording config (TOML, room tasks, output path, danmaku, notifications).
- `bilive-server.toml` — Windows-side processing config (worker idle timeout, upload retry, slice burst params, MiMo, faster-whisper, edit-instruction windows).

Path/config resolution is in [src/config/base.py](src/config/base.py): priority is env var > config file > default. The Windows Worker API additionally auto-loads `.secrets/env` (see `_load_project_env_file` in [src/server/worker_server.py](src/server/worker_server.py)) and sets `BILIVE_CONFIG`, `BILIVE_VIDEOS_DIR`, `BILIVE_DB_PATH`, `BILIVE_COOKIE_FILE`, etc.

Real credentials (`MIMO_API_KEY`, `BLREC_API_KEY`, `BILIVE_WINDOWS_SSH_TARGET`, bilibili cookie) live only in `.secrets/` (gitignored) or untracked config / process env — never in logs, test snapshots, commit messages, or process args. `README.md` documents the `Set-BiliveSecret` helper for writing `.secrets/env`.

Key env vars: `MIMO_API_KEY` (prod slicing), `BILIVE_AUTO_UPLOAD=0`, `BILIVE_WORKER_IDLE_TIMEOUT=0` (diagnostics), `BILIVE_CONFIG`, `BILIVE_VIDEOS_DIR`, `BILIVE_LOG_DIR`, `BILIVE_DB_PATH`, `BILIVE_COOKIE_FILE`.

## Architecture

### Two FastAPI apps

- **Pi dashboard** — [src/dashboard/app.py](src/dashboard/app.py), port 2234, serves [frontend/](frontend/) (vanilla JS: `app.js`, `styles.css`, `index.html`, no build step). Routes: source-recordings index (`/api/source-recordings`), per-recording detail with danmaku-density + candidates, per-segment actions (`/api/segments/{id}/manual-keep|drop|range|retry-judge|render`), Eagle source index (`/api/eagle/source-recordings`), and the read-only upload dashboard (`/api/upload-dashboard`). Background modules: [remote_worker.py](src/dashboard/remote_worker.py) (SSH-start the Windows Worker API on demand), [slice_control.py](src/dashboard/slice_control.py), [source_workbench.py](src/dashboard/source_workbench.py), [task_state.py](src/dashboard/task_state.py), [file_store.py](src/dashboard/file_store.py).
- **Windows Worker API** — [src/server/worker_server.py](src/server/worker_server.py) is the entry; [worker_api.py](src/server/worker_api.py) builds the FastAPI app. Composed modules in `src/server/`: `worker_control.py` (run a one-shot watcher pass), `worker_idle.py` (15-min idle shutdown watchdog), `worker_lock.py` (**cross-process** lock — never replace with a thread lock), `upload_control.py` (single-instance upload consumer), `preflight.py` (validates `MIMO_API_KEY`/ASR cache/SQLite/Videos before work), `watcher.py` (atomically claims pending tasks), `action_jobs.py` (`retry_judge` / `render_segment` action jobs).

### Slice / upload pipeline

```text
danmaku density -> candidate ranges -> MiMo multi-modal judge
  -> drop : delete candidate
  -> keep : single-segment rough cut -> faster-whisper (large-v3, CPU int8) on trimmed audio
          -> ffmpeg rough-cut + subtitle burn -> .upload.json -> SQLite upload_queue
  -> any MiMo/Whisper/render/metadata/enqueue failure : keep for manual review
```

- Candidate analysis: [src/autoslice/](src/autoslice/) — `burst_detector.py`, `candidate_analyzer.py`, `danmaku_slice.py`, `slice_quality_filter.py`, `edit_instruction*.py`. Testable stages are split out in [src/burn/pipeline_stages.py](src/burn/pipeline_stages.py).
- MiMo client / multi-modal SDK: [src/autoslice/mllm_sdk/](src/autoslice/mllm_sdk/).
- Subtitle: [src/subtitle/](src/subtitle/) (`whisper/`, `api/`). Burn + progress: [src/burn/](src/burn/).
- Upload: [src/upload/upload.py](src/upload/upload.py) (CDN upload + web publish), `bilibili_web.py`, `generate_upload_data.py`, `slice_metadata.py`. `bilitool` is a git submodule (upstream — do not edit in place).

### State model & fail-closed

- Recording files: `*.mp4.pending -> *.mp4.processing -> *.mp4.done | *.mp4.failed`
- Dashboard action jobs: `.bilive-jobs/<job>.pending.json -> .processing.json -> .done.json | .failed.json`. Supported actions: `retry_judge`, `render_segment`. Duplicate submits reuse an existing pending/processing job.
- Upload is two resumable stages: after a successful CDN upload, publish retry reuses `remote_filename` so video bytes are never re-uploaded.
- The `upload_queue` SQLite table (see [src/db/conn.py](src/db/conn.py)) enforces a **unique `video_path`**.
- **Fail-closed**: automatic enqueue requires MiMo `keep` + valid single-seg cut + non-empty ASR + valid segment timestamps + successful burn + metadata + SQLite enqueue. Any failure → keep candidate for manual review. Only an explicit MiMo `drop` deletes a candidate.
- Read-only dashboard endpoints must **not** run migrations, create tables, or repair data — return `unavailable` if the DB file is missing.

## Git submodules

- `src/autoslice/auto_slice_video` — upstream [auto-slice-video](https://github.com/timerring/auto-slice-video.git). Build docs live in its own `README.md`; treat as upstream.
- `src/upload/bilitool` — upstream [bilitool](https://github.com/timerring/bilitool.git). Don't modify in place.

Clone with submodules; the reviewing/tests/artifacts under `.worktrees/` are local scratch and gitignored.

## Testing notes

- [pytest.ini](pytest.ini): `testpaths=tests`, default run excludes `integration` and `legacy` markers. `tests/conftest.py` provides `dashboard_client` (in-process FastAPI via `httpx.ASGITransport`) and `videos_root` fixtures — prefer these over touching real `Videos/` paths.
- 48 test files cover dashboard API, action jobs, burst/candidate analysis, MiMo analyzer, pipeline stages, remote worker, recovery, blrec hardening, eagle source index, etc.

## Local runtime artifacts (gitignored)

`Videos/*` (recordings), `logs/*`, `artifacts/`, `.runtime/` (local llama.cpp/llama-server), `src/db/data.db`, `src/subtitle/models/*.pt`, `.secrets/`, `.sisyphus/`, `.worktrees/`. Don't commit these; don't point production paths at them in code.