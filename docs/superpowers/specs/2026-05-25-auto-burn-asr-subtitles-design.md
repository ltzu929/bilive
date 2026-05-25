# Auto Burn ASR Subtitles Design

## Goal

Automatically burn subtitles into generated slice clips by reusing the ASR transcript that is already produced during title and quality analysis.

The first implementation should target the independent slice flow:

`scan_slice.py` -> `slice_only.py` -> `slice_video_by_danmaku()` -> `generate_title()`

It should not run ASR a second time and should not block upload when timestamped subtitles are unavailable.

## Context

The current independent slice flow first cuts candidate clips with ffmpeg stream copy, then calls `generate_title()` for each clip. In `local-audio` and `multi-modal` modes, that call runs ASR through `audio_analyzer.py` and returns an `AnalysisResult` containing:

- `transcript`: full normalized transcript text
- `transcript_segments`: timestamped ASR segments relative to the generated slice clip

Those segments are already used as edit-instruction evidence, but the video file itself remains unsubtitled. The older full-render path has subtitle burning support through `.srt` files and ffmpeg `subtitles=...`, but the independent slice path does not use it.

## Proposed Approach

After a slice is accepted by quality filtering and before upload metadata is written, `slice_only.py` should attempt to burn subtitles into that slice.

The flow should be:

1. `generate_title(slice_path, artist, danmaku_text=...)` returns an `AnalysisResult`.
2. If `result.retain_recommendation` is false, keep the existing removal behavior.
3. If `result.transcript_segments` contains valid timestamped text, write a temporary SRT sidecar for the slice.
4. Run ffmpeg to create a subtitled temporary video.
5. Replace the original slice only after ffmpeg succeeds.
6. Continue metadata writing and upload queue insertion using the final slice path.

If subtitles cannot be generated or ffmpeg fails, log the reason and continue with the original unsubtitled slice. Upload should not be blocked by subtitle burning.

This approach is preferred because it reuses the ASR result already paid for by the title/quality step, keeps the burst detection and initial slicing flow unchanged, and avoids transcription of the whole source recording.

## Components

Add a small helper module under `src/burn/`, with these responsibilities:

- convert `AnalysisResult.transcript_segments` into SRT text,
- clamp or skip invalid segment times,
- write the SRT file with UTF-8 encoding,
- run ffmpeg with a subtitles filter,
- atomically replace the original clip on success.

Keep this helper independent of title generation and upload queue code. `slice_only.py` should only call one high-level function such as `burn_subtitles_from_analysis(slice_path, result)`.

## Data And Timing

ASR segment times from `analyze_audio(slice_path, ...)` are relative to the generated slice clip. The SRT writer should therefore write those times directly as clip-relative timestamps.

Rules:

- skip empty segment text,
- skip segments whose `end <= start`,
- clamp negative starts to `0`,
- preserve segment order,
- write millisecond SRT timestamps,
- return a clear "no subtitles" result when no valid segments remain.

## FFmpeg Behavior

The subtitle burn command should re-encode video and copy or re-encode audio conservatively:

- input: current slice file,
- filter: `subtitles=<srt>:force_style=...`,
- output: temporary file in the same directory,
- success: replace original slice,
- failure: delete temporary output and keep original.

The style can initially reuse the existing subtitle defaults from `render_command.py`: readable bottom subtitles with configured font size and margin. A later UI/style pass can tune font, outline, and positioning.

Because burning subtitles requires re-encoding video, this is intentionally done after quality filtering so rejected clips do not spend extra ffmpeg time.

## Error Handling

Subtitle burning is best effort.

Failure cases should not abort the slice pipeline:

- `AnalysisResult` missing or not timestamped,
- no valid transcript segments,
- SRT write failure,
- ffmpeg missing or failing,
- temporary replacement failure.

Each failure should log enough context to diagnose which clip was affected.

## Testing

Add focused tests for:

- SRT formatting from transcript segments,
- invalid segment filtering and time clamping,
- ffmpeg command construction for subtitle burning,
- successful replacement of the original clip,
- failure fallback that preserves the original clip,
- `slice_only.py` calling subtitle burn only for retained `AnalysisResult` objects with segments.

Existing targeted test groups for slice-only, title generation, and upload metadata should remain passing.

## Out Of Scope

This design does not cover:

- retranscribing source recordings,
- burning subtitles into full-stream renders,
- uploading external subtitle tracks to Bilibili,
- dashboard controls for subtitle style,
- manual subtitle editing,
- changing the initial burst slicing algorithm.
