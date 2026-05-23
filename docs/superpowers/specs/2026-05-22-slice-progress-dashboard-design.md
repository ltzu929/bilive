# Slice Progress Dashboard Design

## Goal

Show live slicing progress on the existing `/tasks` dashboard so the operator can see both:

- the overall pipeline stage for the current recording, and
- the current ffmpeg slice percentage for the active clip.

The first implementation should avoid extra services and avoid writing progress data to the Pi SD card.

## Context

The slice pipeline is:

`scan_slice.py` -> `slice_only.py` -> `slice_video_by_danmaku()` -> `slice_video.py`

The dashboard is a FastAPI app in `src/dashboard/app.py` with a static frontend in `frontend/`. It currently lists completed candidate slices through `/api/slices`; it does not expose active pipeline state.

The project runs from the SMB/CIFS shared project directory:

- Windows path: `D:\alldata\pi\bilive`
- Pi path: `/mnt/win/bilive`

Runtime state written under the project directory lands on the Windows share, not on the Pi SD card.

## Proposed Approach

Use a small JSON progress file as the boundary between the slice process and the dashboard.

Default path:

`logs/runtime/slice-progress.json`

The path should resolve under the runtime/project directory, matching the existing `logs/runtime` convention. This keeps writes on the SMB share in the current deployment.

The slice process writes state at phase transitions and while ffmpeg is running. The dashboard backend reads the file and returns a normalized JSON response. The frontend polls that endpoint and renders a compact progress panel.

This is preferred over WebSocket/SSE for the first version because the current dashboard already uses static HTML and normal JSON APIs. Polling is simpler to debug across Windows, Pi, and CIFS.

## Progress Model

The state file should contain:

- `status`: `idle`, `running`, `complete`, or `error`
- `phase`: stable machine value such as `scan`, `danmaku`, `detect`, `slice`, `analyze`, `metadata`, `queue`, `cleanup`
- `phase_label`: human-readable label for the UI
- `room_id`
- `source_path`
- `source_name`
- `current_slice`
- `total_slices`
- `current_slice_path`
- `current_slice_percent`
- `message`
- `error`
- `updated_at`

For ffmpeg progress, `slice_video.py` should run ffmpeg with `-progress pipe:1` and parse `out_time_ms` or `out_time`. Percentage is:

`processed_seconds / target_duration * 100`

The writer should clamp the value to `0..100` and write at a low frequency, such as no more than twice per second, to avoid unnecessary file churn.

## Backend API

Add:

`GET /api/slice-progress`

Behavior:

- If the file does not exist, return an idle state.
- If JSON is unreadable because the writer is mid-update, return the last known safe default or an idle/error-shaped response without failing the page.
- Include `stale: true` when `updated_at` is old enough that the process likely stopped without cleanup.
- Do not scan large log files for progress.

Writes should be atomic: write to a temporary file in the same directory, then replace the progress file.

## Frontend UI

Add a compact progress band below the toolbar on `/tasks`.

It should show:

- pipeline phase label and message,
- current source file name,
- slice count such as `2/3`,
- current ffmpeg percentage and progress bar,
- error text when status is `error`,
- idle text when no active task is present.

The frontend should poll `/api/slice-progress` every 2 seconds while the page is visible. Existing `/api/slices` refresh can remain at its current cadence.

## SD Card Write Boundary

The progress JSON must be written under the SMB-backed project/runtime directory, not under `/var`, `/tmp`, `/opt`, or the Pi home directory.

Expected write pattern is tiny:

- JSON file size: roughly 1-2 KB
- update rate during ffmpeg: at most 2 writes per second
- phase updates: only a few writes per recording

In the current deployment, these writes land on the Windows share through `/mnt/win/bilive`, so they should not increase Pi SD card wear. The dashboard reads the same small file through CIFS.

## Testing

Backend tests:

- missing progress file returns idle state,
- valid progress file is returned with normalized fields,
- stale progress file is marked stale,
- invalid JSON does not crash the endpoint.

Slice progress tests:

- ffmpeg progress lines are parsed into percentages,
- percentages are clamped,
- progress writer performs atomic writes.

Frontend tests:

- progress endpoint is polled,
- running status renders phase and percentage,
- idle/error states render expected text.

## Out of Scope

- WebSocket or SSE streaming
- persistent history of old slicing tasks
- progress for upload publishing
- moving runtime state off the existing SMB/project directory
