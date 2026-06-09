# Evidence-Driven Slice Pipeline Design

## Goal

Make one authoritative PC-side pipeline implement this sequence:

```text
recording saved
  -> danmaku burst detection
  -> candidate clip
  -> ASR transcript with timestamps
  -> transcript + candidate-window danmaku sent to LLM
  -> LLM keep/drop decision
  -> burn ASR subtitles
  -> enqueue and automatically publish to Bilibili
```

Pi remains recorder-only. All CPU-heavy work stays on Windows.

## Decisions

### One production path

The supported path is:

```text
dashboard .pending marker
  -> src.server.watcher --once
  -> src.burn.slice_only
  -> upload queue
  -> src.upload.upload
```

`watcher` accepts only `action=slice`. The old full-directory `scan_slice`
launcher and the `render` watcher action are removed from supported entry
points. Legacy modules may remain only when they are not reachable from the
normal launcher, worker API, or dashboard.

### One analysis contract

Create a focused candidate analyzer that owns:

1. ASR invocation.
2. Validation that the transcript and timestamped segments are non-empty.
3. Calling the configured LLM judge with both transcript and danmaku text.
4. Returning one `AnalysisResult`.

The production pipeline no longer selects between title-only cloud providers,
heuristic quality scoring, and LLM judging. The configured judge provider is
either OpenAI-compatible or a local subprocess; both receive the same evidence.

### Strict automatic-publish gate

A candidate is automatically queued only when all conditions are true:

- ASR produced non-empty transcript text.
- ASR produced at least one valid timestamped segment.
- Candidate-window danmaku was extracted and supplied to the judge. Empty
  danmaku is allowed only when the source window genuinely contains none; the
  field still appears in the judge request.
- LLM returned a valid response with `judge_status=keep`.
- Subtitle burning completed successfully.
- Upload metadata was written successfully.
- SQLite queue insertion succeeded.

No heuristic score can override an LLM `drop` or failed judge.

### Failure policy

| Failure | Result | Candidate file | Upload |
|---|---|---|---|
| No burst | completed with zero candidates | none | none |
| ASR failure / empty transcript / no timestamps | `judge_failed` review item | keep | no |
| LLM unavailable / invalid JSON | `judge_failed` review item | keep | no |
| LLM `drop` | dropped history item | delete | no |
| Subtitle burn failure | `judge_failed` review item | keep | no |
| Metadata write or queue insert failure | review/error item | keep | no |
| LLM `keep`, subtitle burn and queue succeed | queued | kept until uploader succeeds | yes |

Human `manual_keep` remains an explicit override and may enqueue a review
candidate. This is intentionally separate from automatic publishing.

## Components

### `src/autoslice/candidate_analyzer.py`

Provides `analyze_candidate(video_path, artist, danmaku_text)`. It uses the
existing ASR implementation and the existing LLM judge, but removes title-only
provider routing from the production path.

It also provides batch model cleanup so `slice_only` does not need to know which
model mode was selected.

### `src/burn/slice_only.py`

Remains the orchestration boundary:

- detect burst windows;
- create candidate clips;
- extract window-specific danmaku;
- call `analyze_candidate`;
- record keep/drop/review state;
- burn subtitles for `keep`;
- write upload sidecar and enqueue only after successful burn.

The function continues returning structured diagnostics and segment history for
the dashboard.

### `src/server/watcher.py`

Processes only pending slice tasks. Unknown or historical `render` actions fail
clearly and are recorded in task history.

### Upload consumer

The resumable queue and Bilibili Web submission implementation from the
automatic-upload feature remains independent. It consumes only finalized,
LLM-approved candidates.

## Simplification

- Remove `start_pipeline.ps1 -RunLegacyScanSlice`.
- Remove `src.burn.scan_slice` and its dedicated tests/documentation.
- Stop documenting `mllm_model` as a production switch between incompatible
  analysis semantics.
- Keep old title-provider modules only as unreferenced compatibility code in
  this iteration; deletion is deferred because they have opt-in integration
  tests and are not on the production path.
- Keep full-recording render modules unreachable from `watcher`; they are not
  part of the slice automation goal.

## Verification

Automated evidence must cover:

- ASR transcript and danmaku reach the same LLM judge call.
- Empty ASR does not call the LLM.
- LLM failure does not queue.
- LLM drop deletes the candidate and does not queue.
- LLM keep with successful subtitle burn writes metadata and queues once.
- Subtitle burn failure does not queue.
- Queue insertion failure is not reported as queued.
- Watcher rejects `render`.
- PC launchers contain no legacy full-directory scan path.
- Full offline pytest suite and Python compilation pass.

Real Bilibili publishing is not required for this iteration; the user explicitly
requested feature completion without using a real slice for acceptance.
