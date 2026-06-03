# Slice Workbench And Judge-Failed Flow Design

## Goal

Make the slicing workflow depend on a successful LLM keep/drop decision, then redesign the lower half of `/tasks` around source recordings instead of only generated clips.

The operator should be able to:

- see which source recordings produced keep, judge-failed, skipped, or zero-slice results,
- inspect a source recording with its danmaku-density timeline,
- distinguish LLM-accepted clips from LLM failures at a glance,
- manually resolve judge failures without automatically uploading them.

## Context

The current flow detects danmaku bursts, cuts candidate clips, runs ASR and an LLM judge/title step, burns subtitles, writes metadata, and queues uploads.

The current problem is that LLM judge failures are treated as keep by default. In `src/autoslice/mllm_sdk/judge.py`, fallback results currently return `retain=True` with reasons such as "keeping by default". In `src/burn/slice_only.py`, any `AnalysisResult` with `retain_recommendation=True` continues through subtitle burn and upload queue insertion.

That means a 502, timeout, or JSON parsing failure can produce a clip that appears accepted even though the LLM did not successfully judge it.

## Final Decisions

- LLM failures use fail-closed behavior.
- The stable status for this case is `judge_failed`.
- `judge_failed` does not burn subtitles automatically and does not enter the upload queue.
- Candidate video files for `judge_failed` are retained so the operator can review them quickly.
- `judge_failed` can be manually kept by the operator.
- Manual keep uses fallback title/description metadata and allows editing in the right panel.
- The source-recording workbench uses a left source list, center source preview plus density chart, and right permanent manual handling panel.
- The task queue remains above the workbench, is collapsible, and is expanded by default.
- The danmaku density chart is an area chart using the existing 10-second window.
- Blue solid ranges mean LLM keep.
- Red dashed ranges mean `judge_failed`.
- Clicking a blue or red range seeks the source video to the range start and pauses.
- Upload queue insertion happens only for LLM keep or manual keep.

## Pipeline Behavior

Candidate selection remains based on danmaku bursts. Burst selection is still only a candidate generator, not a final keep decision.

For each candidate:

1. Cut the candidate clip file.
2. Run ASR as configured.
3. Call the LLM judge/title step.
4. If the LLM returns valid JSON and `retain=true`, mark the segment `keep`.
5. If the LLM returns valid JSON and `retain=false`, mark the segment `drop` and remove or ignore the candidate according to existing drop behavior.
6. If the LLM call fails, times out, or cannot be parsed, mark the segment `judge_failed`.
7. Keep `judge_failed` candidate media on disk, but do not burn subtitles, write upload metadata, or insert the upload queue row.
8. Record enough source-window metadata to render the timeline and manual panel.

Manual keep for a `judge_failed` segment should:

- keep or regenerate the candidate clip for the selected time range,
- allow fallback title/description/tags to be edited,
- write the same metadata expected by upload,
- insert the upload queue row only after the operator explicitly saves keep.

## Data Model

The dashboard needs a source-level analysis view in addition to the current task and slice inventory.

Each source recording should expose:

- `source_rel_path`
- `room_id`
- `room_name`
- `source_name`
- `duration_seconds`
- `source_size_mb`
- `task_status`
- `summary_counts`: keep, judge_failed, drop, skipped, review
- `density_points`
- `segments`

Each density point should contain:

- `start_seconds`
- `end_seconds`
- `count`
- optional normalized density value for chart rendering

Each segment should contain:

- `segment_id`
- `source_rel_path`
- `candidate_path`
- `start_seconds`
- `end_seconds`
- `density_core_start`
- `density_core_end`
- `judge_status`: `keep`, `drop`, `judge_failed`, or `manual_keep`
- `judge_error`
- `quality_score`
- `quality_reason`
- `title`
- `description`
- `tags`
- `upload_status`
- `manual_override`

The source-level history can live beside the existing `.mp4.task.json` history or be embedded in it, as long as the dashboard can read it without scanning logs.

## Backend API

Add or extend APIs to support the workbench:

- `GET /api/source-recordings`
  - Returns the left-side source list with counts and task summaries.
- `GET /api/source-recordings/{task_id}`
  - Returns source video metadata, density points, and segments.
- `POST /api/segments/{segment_id}/retry-judge`
  - Re-runs only the judge/title step when enough ASR or source context exists.
- `POST /api/segments/{segment_id}/manual-keep`
  - Saves manual keep metadata and queues upload.
- `POST /api/segments/{segment_id}/drop`
  - Marks the segment dropped and ensures it is not queued.
- `POST /api/segments/{segment_id}/range`
  - Saves adjusted start/end range without immediately rendering.
- `POST /api/segments/{segment_id}/render`
  - Renders or re-renders the adjusted clip when the operator asks.

Existing `/api/tasks` should remain for the top queue panel. It can include richer summary text, but the detailed chart data belongs to the source-recording endpoints.

## Frontend Layout

The `/tasks` page keeps the current progress and diagnostics areas at the top.

Below that:

- Task queue panel:
  - collapsible,
  - expanded by default,
  - compact table layout,
  - summarizes keep and judge-failed counts.
- Workbench:
  - left: source recording list,
  - center: source video preview and danmaku density area chart,
  - right: permanent manual handling panel.

The source list should show compact status badges:

- keep count,
- judge_failed count,
- skipped or zero-slice status,
- task status.

The center area chart should:

- render an area shape from 10-second density points,
- overlay blue solid keep regions,
- overlay red dashed judge-failed regions,
- support click-to-seek to the region start,
- pause the source video after seeking,
- select the corresponding segment in the right panel.

The right panel should show:

- selected segment status,
- source time range,
- candidate clip path if present,
- LLM score/reason when present,
- judge error when failed,
- fallback title/description/tags,
- actions: retry LLM, manual keep, drop, adjust in/out, render adjusted clip.

## Error Handling

LLM judge errors must be visible and durable:

- network errors,
- 502 or other HTTP errors,
- timeout,
- JSON parse failure,
- malformed response.

These errors should not be collapsed into successful keep decisions. They should be written into segment metadata and visible in the right panel.

Manual keep must be explicit. A failed judge segment should not enter upload because the page was refreshed or because fallback metadata exists.

## Testing

Backend tests:

- LLM exception produces `judge_failed`, not keep.
- LLM JSON parse failure produces `judge_failed`, not keep.
- `judge_failed` candidate media is retained.
- `judge_failed` is not inserted into the upload queue.
- manual keep inserts the upload queue row.
- source recording endpoint returns density points and segment overlays.
- retry judge updates `judge_failed` to keep/drop when successful.

Frontend tests:

- task queue can collapse and is expanded by default.
- source list renders keep and judge-failed badges.
- area chart renders density data.
- keep segments render as blue overlays.
- judge-failed segments render as red dashed overlays.
- clicking an overlay seeks and pauses the source video.
- right panel exposes retry, manual keep, drop, range adjustment, and render actions.

Integration tests:

- a failed LLM call never appears as a blue keep range.
- a manual keep changes the range to an uploadable state.
- a source with no burst segments shows an empty chart state rather than candidate clips.

## Out Of Scope

- Moving ASR to the GPU.
- Replacing the danmaku burst algorithm.
- Upload workflow redesign beyond queue insertion rules.
- WebSocket/SSE live streaming.
- Full video editor timeline behavior.
- Deleting old generated clips automatically.
