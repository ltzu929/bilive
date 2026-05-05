# Slice Edit Instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate per-slice structured edit instruction JSON files first, then optional model-ready prompt files, using the existing danmaku-density slicing and Whisper-backed analysis pipeline.

**Architecture:** Add focused autoslice modules for edit instruction data, instruction building, and prompt packaging. Keep `AnalysisResult` responsible for content understanding and quality scoring, while `EditInstruction` owns automatic editing controls. Integrate the writer after quality filtering in both slice-only and rendered auto-slice paths without changing upload behavior when instruction generation fails.

**Tech Stack:** Python dataclasses, json, pathlib, re, existing `pysrt`, existing TOML config loader, pytest.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/autoslice/edit_instruction.py` | Dataclasses for trim, segments, subtitle evidence, danmaku evidence, upload suggestion, and the final instruction JSON. |
| `src/autoslice/edit_instruction_builder.py` | Build an `EditInstruction` from `AnalysisResult`, slice path, source path, optional subtitle file, and slice timing inferred from filename. |
| `src/autoslice/prompt_packager.py` | Convert an `EditInstruction` JSON file into a markdown prompt for a second model pass. |
| `src/autoslice/__init__.py` | Export the new public instruction types and helpers. |
| `src/config.py` | Read `[slice.edit]` configuration values. |
| `bilive.toml` | Document default `[slice.edit]` settings. |
| `src/burn/slice_only.py` | Write `_edit.json` and optional `_prompt.md` after quality filtering succeeds. |
| `src/burn/render_video.py` | Use the same instruction writer in the rendered auto-slice branch. |
| `tests/test_edit_instruction.py` | Focused unit tests for data model, builder, prompt packager, and disabled config behavior. |

---

## Task 1: Add EditInstruction Data Model

**Files:**
- Create: `src/autoslice/edit_instruction.py`
- Test: `tests/test_edit_instruction.py`

- [ ] **Step 1: Write failing data model tests**

Create `tests/test_edit_instruction.py` with:

```python
import json
from pathlib import Path

from src.autoslice.edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TrimInstruction,
    UploadSuggestion,
)


def test_edit_instruction_round_trip_dict():
    instruction = EditInstruction(
        source_video="Videos/room/source.mp4",
        slice_video="Videos/room/12s_source.mp4",
        decision="keep",
        confidence=0.82,
        trim=TrimInstruction(start=2.5, end=58.0, reason="remove quiet opening"),
        segments=[
            EditSegment(
                start=8.0,
                end=18.5,
                type="highlight",
                score=0.9,
                reason="danmaku peak and useful transcript",
            )
        ],
        subtitle_evidence=[
            SubtitleEvidence(start=7.2, end=10.8, text="important transcript")
        ],
        danmaku_evidence=DanmakuEvidence(
            peak_time=12.0,
            density_reason="slice selected by danmaku density",
        ),
        edit_actions=["Keep 8.0-18.5 as the main highlight"],
        upload_suggestion=UploadSuggestion(
            title="Good clip",
            description="A useful clip",
            tags=["live", "highlight"],
        ),
    )

    data = instruction.to_dict()
    restored = EditInstruction.from_dict(data)

    assert restored.schema_version == "1.0"
    assert restored.decision == "keep"
    assert restored.confidence == 0.82
    assert restored.trim.start == 2.5
    assert restored.segments[0].reason == "danmaku peak and useful transcript"
    assert restored.subtitle_evidence[0].text == "important transcript"
    assert restored.upload_suggestion.tags == ["live", "highlight"]


def test_edit_instruction_to_json_file(tmp_path):
    output_path = tmp_path / "clip_edit.json"
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="12s_source.mp4",
        decision="review",
        confidence=0.5,
    )

    assert instruction.to_json_file(output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["decision"] == "review"
    assert data["slice_video"] == "12s_source.mp4"


def test_invalid_decision_falls_back_to_review():
    instruction = EditInstruction.from_dict(
        {
            "source_video": "source.mp4",
            "slice_video": "clip.mp4",
            "decision": "unknown",
            "confidence": 3.0,
        }
    )

    assert instruction.decision == "review"
    assert instruction.confidence == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_edit_instruction.py -v
```

If running in WSL with the repo venv, use:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: fail with `ModuleNotFoundError: No module named 'src.autoslice.edit_instruction'`.

- [ ] **Step 3: Implement the data model**

Create `src/autoslice/edit_instruction.py`:

```python
# Copyright (c) 2024 bilive.

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List

from src.log.logger import scan_log


VALID_DECISIONS = {"keep", "review", "drop"}


def _clamp_score(value: Any, default: float = 0.5) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TrimInstruction:
    start: float = 0.0
    end: float = 0.0
    reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrimInstruction":
        return cls(
            start=_as_float(data.get("start", 0.0)),
            end=_as_float(data.get("end", 0.0)),
            reason=str(data.get("reason", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "reason": self.reason}


@dataclass
class EditSegment:
    start: float = 0.0
    end: float = 0.0
    type: str = "highlight"
    score: float = 0.5
    reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EditSegment":
        return cls(
            start=_as_float(data.get("start", 0.0)),
            end=_as_float(data.get("end", 0.0)),
            type=str(data.get("type", "highlight")),
            score=_clamp_score(data.get("score", 0.5)),
            reason=str(data.get("reason", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "type": self.type,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class SubtitleEvidence:
    start: float = 0.0
    end: float = 0.0
    text: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubtitleEvidence":
        return cls(
            start=_as_float(data.get("start", 0.0)),
            end=_as_float(data.get("end", 0.0)),
            text=str(data.get("text", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class DanmakuEvidence:
    peak_time: float = 0.0
    density_reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DanmakuEvidence":
        return cls(
            peak_time=_as_float(data.get("peak_time", 0.0)),
            density_reason=str(data.get("density_reason", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peak_time": self.peak_time,
            "density_reason": self.density_reason,
        }


@dataclass
class UploadSuggestion:
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadSuggestion":
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return cls(
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            tags=[str(tag) for tag in tags],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
        }


@dataclass
class EditInstruction:
    source_video: str
    slice_video: str
    decision: str = "review"
    confidence: float = 0.5
    trim: TrimInstruction = field(default_factory=TrimInstruction)
    segments: List[EditSegment] = field(default_factory=list)
    subtitle_evidence: List[SubtitleEvidence] = field(default_factory=list)
    danmaku_evidence: DanmakuEvidence = field(default_factory=DanmakuEvidence)
    edit_actions: List[str] = field(default_factory=list)
    upload_suggestion: UploadSuggestion = field(default_factory=UploadSuggestion)
    schema_version: str = "1.0"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EditInstruction":
        decision = str(data.get("decision", "review"))
        if decision not in VALID_DECISIONS:
            decision = "review"

        return cls(
            source_video=str(data.get("source_video", "")),
            slice_video=str(data.get("slice_video", "")),
            decision=decision,
            confidence=_clamp_score(data.get("confidence", 0.5)),
            trim=TrimInstruction.from_dict(data.get("trim", {}) or {}),
            segments=[
                EditSegment.from_dict(item)
                for item in data.get("segments", [])
                if isinstance(item, dict)
            ],
            subtitle_evidence=[
                SubtitleEvidence.from_dict(item)
                for item in data.get("subtitle_evidence", [])
                if isinstance(item, dict)
            ],
            danmaku_evidence=DanmakuEvidence.from_dict(
                data.get("danmaku_evidence", {}) or {}
            ),
            edit_actions=[
                str(action)
                for action in data.get("edit_actions", [])
                if str(action).strip()
            ],
            upload_suggestion=UploadSuggestion.from_dict(
                data.get("upload_suggestion", {}) or {}
            ),
            schema_version=str(data.get("schema_version", "1.0")),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "EditInstruction":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_video": self.source_video,
            "slice_video": self.slice_video,
            "decision": self.decision,
            "confidence": self.confidence,
            "trim": self.trim.to_dict(),
            "segments": [segment.to_dict() for segment in self.segments],
            "subtitle_evidence": [
                evidence.to_dict() for evidence in self.subtitle_evidence
            ],
            "danmaku_evidence": self.danmaku_evidence.to_dict(),
            "edit_actions": self.edit_actions,
            "upload_suggestion": self.upload_suggestion.to_dict(),
        }

    def to_json_file(self, output_path: str | Path) -> bool:
        try:
            path = Path(output_path)
            path.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except (OSError, TypeError) as exc:
            scan_log.error(f"Failed to write edit instruction '{output_path}': {exc}")
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests in `tests/test_edit_instruction.py` pass.

- [ ] **Step 5: Commit**

```bash
git add src/autoslice/edit_instruction.py tests/test_edit_instruction.py
git commit -m "feat: add edit instruction data model"
```

---

## Task 2: Build EditInstruction from AnalysisResult

**Files:**
- Create: `src/autoslice/edit_instruction_builder.py`
- Modify: `tests/test_edit_instruction.py`

- [ ] **Step 1: Add failing builder tests**

Append to `tests/test_edit_instruction.py`:

```python
from src.autoslice.analysis_result import AnalysisResult, Highlight, TrimSuggestion
from src.autoslice.edit_instruction_builder import (
    build_edit_instruction,
    infer_slice_start_seconds,
    read_srt_evidence,
)


def test_infer_slice_start_seconds_from_autosv_name():
    assert infer_slice_start_seconds("/Videos/room/123s_record.mp4") == 123.0
    assert infer_slice_start_seconds("/Videos/room/0s_record.mp4") == 0.0
    assert infer_slice_start_seconds("/Videos/room/record.mp4") == 0.0


def test_build_edit_instruction_from_highlights_and_trim():
    result = AnalysisResult(
        title="Clip title",
        description="Clip description",
        tags=["tag1", "tag2"],
        quality_score=0.84,
        retain_recommendation=True,
        quality_reason="good reaction",
        highlights=[
            Highlight(start=7.0, end=15.0, score=0.92, desc="best moment")
        ],
        emotion_peak_time=11.0,
        suggested_trim=TrimSuggestion(
            trim_start=2.0,
            trim_end=55.0,
            reason="remove quiet edges",
        ),
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="/Videos/room/record.mp4",
        slice_video="/Videos/room/123s_record.mp4",
        slice_duration=60.0,
        subtitle_evidence=[],
    )

    assert instruction.decision == "keep"
    assert instruction.confidence == 0.84
    assert instruction.trim.start == 2.0
    assert instruction.trim.end == 55.0
    assert instruction.segments[0].start == 7.0
    assert instruction.segments[0].end == 15.0
    assert instruction.segments[0].reason == "best moment"
    assert instruction.danmaku_evidence.peak_time == 11.0
    assert instruction.upload_suggestion.title == "Clip title"
    assert "Keep 7.0-15.0 as the main highlight" in instruction.edit_actions


def test_build_edit_instruction_degrades_without_subtitles():
    result = AnalysisResult(
        title="Needs review",
        description="A transcript-like description",
        quality_score=0.52,
        retain_recommendation=True,
        quality_reason="audio only",
        emotion_peak_time=0.0,
    )

    instruction = build_edit_instruction(
        analysis=result,
        source_video="source.mp4",
        slice_video="0s_source.mp4",
        slice_duration=60.0,
        subtitle_evidence=[],
    )

    assert instruction.decision == "keep"
    assert instruction.segments[0].start == 0.0
    assert instruction.segments[0].end == 12.0
    assert instruction.subtitle_evidence == []
    assert "Subtitle evidence is missing; review transcript manually" in instruction.edit_actions


def test_read_srt_evidence_limits_items(tmp_path):
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "first line\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:06,000\n"
        "second line\n\n",
        encoding="utf-8",
    )

    evidence = read_srt_evidence(srt_path, max_items=1)

    assert len(evidence) == 1
    assert evidence[0].start == 1.0
    assert evidence[0].end == 3.0
    assert evidence[0].text == "first line"
```

- [ ] **Step 2: Run builder tests to verify they fail**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: fail with `ModuleNotFoundError: No module named 'src.autoslice.edit_instruction_builder'`.

- [ ] **Step 3: Implement the builder**

Create `src/autoslice/edit_instruction_builder.py`:

```python
# Copyright (c) 2024 bilive.

from pathlib import Path
import re
from typing import Iterable, List

import pysrt

from src.autoslice.analysis_result import AnalysisResult
from src.autoslice.edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TrimInstruction,
    UploadSuggestion,
)
from src.log.logger import scan_log


DEFAULT_HIGHLIGHT_WINDOW_SECONDS = 12.0


def infer_slice_start_seconds(slice_video: str) -> float:
    name = Path(slice_video).name
    match = re.match(r"^(\d+(?:\.\d+)?)s_", name)
    if not match:
        return 0.0
    return float(match.group(1))


def clamp_time(value: float, duration: float) -> float:
    return max(0.0, min(float(duration), float(value)))


def read_srt_evidence(srt_path: str | Path, max_items: int = 6) -> List[SubtitleEvidence]:
    path = Path(srt_path)
    if not path.is_file():
        return []

    try:
        subtitles = pysrt.open(str(path), encoding="utf-8")
    except Exception as exc:
        scan_log.warning(f"Failed to read subtitle evidence from {path}: {exc}")
        return []

    evidence = []
    for item in subtitles:
        text = " ".join(str(item.text).split())
        if not text:
            continue
        evidence.append(
            SubtitleEvidence(
                start=item.start.ordinal / 1000,
                end=item.end.ordinal / 1000,
                text=text,
            )
        )
        if len(evidence) >= max_items:
            break

    return evidence


def build_segments(
    analysis: AnalysisResult,
    slice_duration: float,
    default_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> List[EditSegment]:
    segments = []
    for highlight in analysis.highlights:
        start = clamp_time(highlight.start, slice_duration)
        end = clamp_time(highlight.end, slice_duration)
        if end <= start:
            continue
        segments.append(
            EditSegment(
                start=start,
                end=end,
                type="highlight",
                score=max(0.0, min(1.0, float(highlight.score))),
                reason=highlight.desc or "highlight from analysis result",
            )
        )

    if segments:
        return segments

    peak = clamp_time(analysis.emotion_peak_time or 0.0, slice_duration)
    half_window = default_window / 2
    start = clamp_time(peak - half_window, slice_duration)
    end = clamp_time(start + default_window, slice_duration)
    if end <= start:
        end = slice_duration

    return [
        EditSegment(
            start=start,
            end=end,
            type="highlight",
            score=max(0.0, min(1.0, float(analysis.quality_score))),
            reason="fallback highlight window around danmaku-selected slice",
        )
    ]


def build_trim(analysis: AnalysisResult, slice_duration: float) -> TrimInstruction:
    if analysis.suggested_trim is None:
        return TrimInstruction(
            start=0.0,
            end=float(slice_duration),
            reason="keep full slice because no trim suggestion was provided",
        )

    start = clamp_time(analysis.suggested_trim.trim_start, slice_duration)
    end = clamp_time(analysis.suggested_trim.trim_end, slice_duration)
    if end <= start:
        start = 0.0
        end = float(slice_duration)

    return TrimInstruction(
        start=start,
        end=end,
        reason=analysis.suggested_trim.reason,
    )


def build_edit_actions(
    segments: Iterable[EditSegment],
    trim: TrimInstruction,
    subtitle_evidence: List[SubtitleEvidence],
) -> List[str]:
    actions = []
    segment_list = list(segments)
    if segment_list:
        primary = segment_list[0]
        actions.append(
            f"Keep {primary.start:.1f}-{primary.end:.1f} as the main highlight"
        )

    if trim.start > 0:
        actions.append(f"Remove opening 0.0-{trim.start:.1f} seconds")
    if trim.reason:
        actions.append(f"Trim reason: {trim.reason}")

    if not subtitle_evidence:
        actions.append("Subtitle evidence is missing; review transcript manually")

    return actions


def build_edit_instruction(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    slice_duration: float,
    subtitle_evidence: List[SubtitleEvidence] | None = None,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> EditInstruction:
    subtitle_evidence = subtitle_evidence or []
    segments = build_segments(analysis, slice_duration, default_highlight_window)
    trim = build_trim(analysis, slice_duration)
    decision = "keep" if analysis.retain_recommendation else "drop"

    return EditInstruction(
        source_video=str(source_video),
        slice_video=str(slice_video),
        decision=decision,
        confidence=max(0.0, min(1.0, float(analysis.quality_score))),
        trim=trim,
        segments=segments,
        subtitle_evidence=subtitle_evidence,
        danmaku_evidence=DanmakuEvidence(
            peak_time=analysis.emotion_peak_time or infer_slice_start_seconds(slice_video),
            density_reason="slice selected by danmaku density",
        ),
        edit_actions=build_edit_actions(segments, trim, subtitle_evidence),
        upload_suggestion=UploadSuggestion(
            title=analysis.title,
            description=analysis.description,
            tags=analysis.tags,
        ),
    )


def build_and_write_edit_instruction(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    slice_duration: float,
    subtitle_path: str | Path | None = None,
    max_subtitle_evidence: int = 6,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> str | None:
    subtitle_evidence = []
    if subtitle_path:
        subtitle_evidence = read_srt_evidence(subtitle_path, max_subtitle_evidence)

    instruction = build_edit_instruction(
        analysis=analysis,
        source_video=source_video,
        slice_video=slice_video,
        slice_duration=slice_duration,
        subtitle_evidence=subtitle_evidence,
        default_highlight_window=default_highlight_window,
    )
    output_path = str(Path(slice_video).with_suffix("")) + "_edit.json"
    if instruction.to_json_file(output_path):
        scan_log.info(f"Edit instruction saved: {output_path}")
        return output_path
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/autoslice/edit_instruction_builder.py tests/test_edit_instruction.py
git commit -m "feat: build edit instructions from slice analysis"
```

---

## Task 3: Add Prompt Packager for Stage C

**Files:**
- Create: `src/autoslice/prompt_packager.py`
- Modify: `tests/test_edit_instruction.py`

- [ ] **Step 1: Add failing prompt packager tests**

Append to `tests/test_edit_instruction.py`:

```python
from src.autoslice.prompt_packager import build_prompt_markdown, write_prompt_package


def test_build_prompt_markdown_contains_instruction_json():
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="12s_source.mp4",
        decision="keep",
        confidence=0.9,
        subtitle_evidence=[
            SubtitleEvidence(start=1.0, end=3.0, text="important transcript")
        ],
    )

    prompt = build_prompt_markdown(instruction, artist="Streamer")

    assert "# Slice Editing Follow-up Prompt" in prompt
    assert "Streamer" in prompt
    assert '"decision": "keep"' in prompt
    assert "important transcript" in prompt
    assert "Return JSON only" in prompt


def test_write_prompt_package(tmp_path):
    edit_path = tmp_path / "clip_edit.json"
    instruction = EditInstruction(
        source_video="source.mp4",
        slice_video="clip.mp4",
        decision="review",
        confidence=0.5,
    )
    instruction.to_json_file(edit_path)

    prompt_path = write_prompt_package(edit_path, artist="Streamer")

    assert prompt_path == str(tmp_path / "clip_prompt.md")
    assert Path(prompt_path).is_file()
    assert "clip.mp4" in Path(prompt_path).read_text(encoding="utf-8")
```

- [ ] **Step 2: Run prompt tests to verify they fail**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: fail with `ModuleNotFoundError: No module named 'src.autoslice.prompt_packager'`.

- [ ] **Step 3: Implement the prompt packager**

Create `src/autoslice/prompt_packager.py`:

```python
# Copyright (c) 2024 bilive.

import json
from pathlib import Path

from src.autoslice.edit_instruction import EditInstruction
from src.log.logger import scan_log


def build_prompt_markdown(
    instruction: EditInstruction,
    artist: str = "",
    max_subtitle_chars: int = 1200,
) -> str:
    instruction_json = json.dumps(
        instruction.to_dict(),
        ensure_ascii=False,
        indent=2,
    )
    subtitle_text = "\n".join(
        f"- {item.start:.1f}-{item.end:.1f}: {item.text}"
        for item in instruction.subtitle_evidence
    )
    if len(subtitle_text) > max_subtitle_chars:
        subtitle_text = subtitle_text[:max_subtitle_chars].rstrip() + "\n- [truncated]"
    if not subtitle_text:
        subtitle_text = "- No subtitle evidence was available for this slice."

    return f"""# Slice Editing Follow-up Prompt

## Context

Artist: {artist or "unknown"}
Source video: {instruction.source_video}
Slice video: {instruction.slice_video}

## Structured Edit Instruction

```json
{instruction_json}
```

## Subtitle Evidence

{subtitle_text}

## Task

Use the structured edit instruction and evidence to produce a second-pass editing plan.
Return JSON only. Keep all time values in seconds relative to the slice video.
Do not invent transcript lines that are not present in the evidence.
"""


def write_prompt_package(edit_json_path: str | Path, artist: str = "") -> str | None:
    path = Path(edit_json_path)
    try:
        instruction = EditInstruction.from_json_file(path)
        prompt = build_prompt_markdown(instruction, artist=artist)
        output_path = path.with_name(path.name.replace("_edit.json", "_prompt.md"))
        if output_path == path:
            output_path = path.with_suffix(".prompt.md")
        output_path.write_text(prompt, encoding="utf-8")
        scan_log.info(f"Prompt package saved: {output_path}")
        return str(output_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        scan_log.error(f"Failed to write prompt package for '{edit_json_path}': {exc}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/autoslice/prompt_packager.py tests/test_edit_instruction.py
git commit -m "feat: package edit instructions for model prompts"
```

---

## Task 4: Add Config and Public Exports

**Files:**
- Modify: `src/config.py`
- Modify: `bilive.toml`
- Modify: `src/autoslice/__init__.py`
- Modify: `tests/test_edit_instruction.py`

- [ ] **Step 1: Add focused import/config tests**

Append to `tests/test_edit_instruction.py`:

```python
def test_autoslice_exports_edit_instruction_types():
    from src.autoslice import EditInstruction as ExportedEditInstruction
    from src.autoslice import build_edit_instruction as exported_builder

    assert ExportedEditInstruction is EditInstruction
    assert exported_builder is build_edit_instruction
```

- [ ] **Step 2: Run export test to verify it fails**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py::test_autoslice_exports_edit_instruction_types -v
```

Expected: fail because `src.autoslice` does not export `EditInstruction` yet.

- [ ] **Step 3: Add config values**

Modify `src/config.py` after the existing `MULTI_MODAL_EMOTION_MODEL` setting:

```python
# Edit instruction configuration
EDIT_ENABLE_INSTRUCTION = config.get("slice", {}).get("edit", {}).get("enable_edit_instruction", True)
EDIT_ENABLE_PROMPT_PACKAGE = config.get("slice", {}).get("edit", {}).get("enable_prompt_package", False)
EDIT_MAX_SUBTITLE_EVIDENCE = config.get("slice", {}).get("edit", {}).get("max_subtitle_evidence", 6)
EDIT_DEFAULT_HIGHLIGHT_WINDOW = config.get("slice", {}).get("edit", {}).get("default_highlight_window", 12)
```

Modify `bilive.toml` after `[slice.multi_modal]` and its emotion settings:

```toml
[slice.edit]
enable_edit_instruction = true
enable_prompt_package = false
max_subtitle_evidence = 6
default_highlight_window = 12
```

- [ ] **Step 4: Export public types and helpers**

Modify `src/autoslice/__init__.py`:

```python
# Copyright (c) 2024 bilive.

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from .auto_slice_video.autosv import slice_video_by_danmaku
from .analysis_result import AnalysisResult, Highlight, TrimSuggestion
from .slice_quality_filter import should_retain_slice
from .edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TrimInstruction,
    UploadSuggestion,
)
from .edit_instruction_builder import build_edit_instruction, build_and_write_edit_instruction
from .prompt_packager import build_prompt_markdown, write_prompt_package

__all__ = [
    "slice_video_by_danmaku",
    "AnalysisResult",
    "Highlight",
    "TrimSuggestion",
    "should_retain_slice",
    "DanmakuEvidence",
    "EditInstruction",
    "EditSegment",
    "SubtitleEvidence",
    "TrimInstruction",
    "UploadSuggestion",
    "build_edit_instruction",
    "build_and_write_edit_instruction",
    "build_prompt_markdown",
    "write_prompt_package",
]
```

- [ ] **Step 5: Run tests**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/config.py bilive.toml src/autoslice/__init__.py tests/test_edit_instruction.py
git commit -m "feat: add edit instruction configuration"
```

---

## Task 5: Integrate EditInstruction Writing into Slice Pipelines

**Files:**
- Modify: `src/burn/slice_only.py`
- Modify: `src/burn/render_video.py`
- Modify: `tests/test_edit_instruction.py`

- [ ] **Step 1: Add unit test for disabled writer helper**

Append to `tests/test_edit_instruction.py`:

```python
from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs


def test_maybe_write_edit_outputs_respects_disabled_flag(tmp_path):
    result = AnalysisResult(
        title="Clip",
        description="Description",
        quality_score=0.8,
        retain_recommendation=True,
    )
    slice_path = tmp_path / "0s_source.mp4"
    slice_path.write_bytes(b"fake")

    output = maybe_write_edit_outputs(
        analysis=result,
        source_video="source.mp4",
        slice_video=str(slice_path),
        artist="Streamer",
        slice_duration=60,
        enable_edit_instruction=False,
        enable_prompt_package=True,
    )

    assert output is None
    assert not (tmp_path / "0s_source_edit.json").exists()
    assert not (tmp_path / "0s_source_prompt.md").exists()
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py::test_maybe_write_edit_outputs_respects_disabled_flag -v
```

Expected: fail with `ImportError` because `maybe_write_edit_outputs` does not exist.

- [ ] **Step 3: Add pipeline-safe writer helper**

Append to `src/autoslice/edit_instruction_builder.py`:

```python
def maybe_write_edit_outputs(
    analysis: AnalysisResult,
    source_video: str,
    slice_video: str,
    artist: str,
    slice_duration: float,
    subtitle_path: str | Path | None = None,
    enable_edit_instruction: bool = True,
    enable_prompt_package: bool = False,
    max_subtitle_evidence: int = 6,
    default_highlight_window: float = DEFAULT_HIGHLIGHT_WINDOW_SECONDS,
) -> str | None:
    if not enable_edit_instruction:
        return None

    try:
        edit_path = build_and_write_edit_instruction(
            analysis=analysis,
            source_video=source_video,
            slice_video=slice_video,
            slice_duration=slice_duration,
            subtitle_path=subtitle_path,
            max_subtitle_evidence=max_subtitle_evidence,
            default_highlight_window=default_highlight_window,
        )
        if edit_path and enable_prompt_package:
            from src.autoslice.prompt_packager import write_prompt_package

            write_prompt_package(edit_path, artist=artist)
        return edit_path
    except Exception as exc:
        scan_log.error(f"Failed to generate edit outputs for {slice_video}: {exc}")
        return None
```

- [ ] **Step 4: Run helper test**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py::test_maybe_write_edit_outputs_respects_disabled_flag -v
```

Expected: pass.

- [ ] **Step 5: Integrate into `src/burn/slice_only.py`**

In the `AnalysisResult` branch after quality filtering succeeds and before `slice_title = result.title`, insert:

```python
                        from src.config import (
                            EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                            EDIT_ENABLE_INSTRUCTION,
                            EDIT_ENABLE_PROMPT_PACKAGE,
                            EDIT_MAX_SUBTITLE_EVIDENCE,
                            SLICE_DURATION,
                        )
                        from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs

                        maybe_write_edit_outputs(
                            analysis=result,
                            source_video=original_video_path,
                            slice_video=slice_path,
                            artist=artist,
                            slice_duration=SLICE_DURATION,
                            enable_edit_instruction=EDIT_ENABLE_INSTRUCTION,
                            enable_prompt_package=EDIT_ENABLE_PROMPT_PACKAGE,
                            max_subtitle_evidence=EDIT_MAX_SUBTITLE_EVIDENCE,
                            default_highlight_window=EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                        )
```

Do not pass a subtitle path in the first integration because the current slice-only flow does not write per-slice SRT files. The builder still emits a valid `_edit.json` with degraded subtitle evidence.

- [ ] **Step 6: Integrate into `src/burn/render_video.py`**

In the `AnalysisResult` branch after quality filtering succeeds and before `slice_title = result.title`, insert:

```python
                        from src.config import (
                            EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                            EDIT_ENABLE_INSTRUCTION,
                            EDIT_ENABLE_PROMPT_PACKAGE,
                            EDIT_MAX_SUBTITLE_EVIDENCE,
                            SLICE_DURATION,
                        )
                        from src.autoslice.edit_instruction_builder import maybe_write_edit_outputs

                        maybe_write_edit_outputs(
                            analysis=result,
                            source_video=format_video_path,
                            slice_video=slice_path,
                            artist=artist,
                            slice_duration=SLICE_DURATION,
                            subtitle_path=srt_path if os.path.exists(srt_path) else None,
                            enable_edit_instruction=EDIT_ENABLE_INSTRUCTION,
                            enable_prompt_package=EDIT_ENABLE_PROMPT_PACKAGE,
                            max_subtitle_evidence=EDIT_MAX_SUBTITLE_EVIDENCE,
                            default_highlight_window=EDIT_DEFAULT_HIGHLIGHT_WINDOW,
                        )
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Run import smoke test**

Run:

```bash
venv/bin/python -c "from src.autoslice import EditInstruction, build_edit_instruction; print('Import OK')"
```

Expected output:

```text
Import OK
```

- [ ] **Step 9: Commit**

```bash
git add src/autoslice/edit_instruction_builder.py src/burn/slice_only.py src/burn/render_video.py tests/test_edit_instruction.py
git commit -m "feat: write edit instructions for generated slices"
```

---

## Task 6: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run edit instruction tests**

```bash
venv/bin/python -m pytest tests/test_edit_instruction.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run existing autoslice data model tests**

```bash
venv/bin/python -m pytest tests/test_autoslice.py::TestAnalysisResult tests/test_autoslice.py::TestSliceQualityFilter -v
```

Expected: selected tests pass. Do not run the API-backed `TestGeminiMain`, `TestQwenMain`, `TestSenseNovaMain`, `TestZhipuMain`, or `TestQwenOmniMain` classes unless valid external credentials and sample videos are configured.

- [ ] **Step 3: Run whitespace check**

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: Inspect worktree**

```bash
git status --short
```

Expected: only the pre-existing `record.sh` local modification remains, unless the user has asked to handle it.

- [ ] **Step 5: Final commit if verification changed files**

If final verification required a small fix, commit only the slice edit instruction files:

```bash
git add src/autoslice/edit_instruction.py src/autoslice/edit_instruction_builder.py src/autoslice/prompt_packager.py src/autoslice/__init__.py src/config.py bilive.toml src/burn/slice_only.py src/burn/render_video.py tests/test_edit_instruction.py
git commit -m "fix: stabilize slice edit instruction output"
```

---

## Self Review

- Spec coverage: Stage B is implemented by Tasks 1, 2, 4, and 5. Stage C is implemented by Task 3 and optionally enabled in Task 5. Config, exports, degradation behavior, and tests are covered.
- Unresolved-marker scan: The plan contains concrete file paths, code blocks, commands, expected failures, expected passes, and commit messages.
- Type consistency: `EditInstruction`, `TrimInstruction`, `EditSegment`, `SubtitleEvidence`, `DanmakuEvidence`, `UploadSuggestion`, `build_edit_instruction`, `build_and_write_edit_instruction`, and `maybe_write_edit_outputs` are used consistently across tasks.
- Scope: The plan writes instruction and prompt artifacts only. It does not implement actual video re-cutting, transitions, BGM, subtitle burn-in, or model API calls.
