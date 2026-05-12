# Copyright (c) 2024 bilive.

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

from src.autoslice.edit_instruction import (
    EditInstruction,
    TimeRange,
    TrimInstruction,
)
from src.autoslice.edit_instruction_builder import infer_slice_start_seconds
from src.db.conn import insert_upload_queue
from src.log.logger import scan_log


VALID_DECISIONS = {"keep", "drop", "review"}


@dataclass
class RefineRange:
    input_path: Path
    input_start: float
    source_start: float
    source_end: float
    duration: float
    reason: str


@dataclass
class FeedbackRefineResult:
    feedback_path: str
    decision: str
    status: str
    refined_clip: str | None = None
    edit_json: str | None = None
    queued: bool = False
    message: str = ""


def process_feedback_directory(
    videos_root: str | Path,
    enqueue_upload: bool = True,
) -> list[FeedbackRefineResult]:
    root = Path(videos_root)
    results = []
    for feedback_path in sorted(root.rglob("*_feedback.json")):
        if ".dashboard-cache" in feedback_path.parts:
            continue
        results.append(
            process_feedback_file(
                feedback_path,
                enqueue_upload=enqueue_upload,
            )
        )
    return results


def process_feedback_file(
    feedback_path: str | Path,
    enqueue_upload: bool = True,
) -> FeedbackRefineResult:
    feedback_path = Path(feedback_path)
    feedback = _read_json(feedback_path)
    decision = _normalize_decision(feedback.get("decision"))
    if decision != "keep":
        return FeedbackRefineResult(
            feedback_path=str(feedback_path),
            decision=decision,
            status="skipped_decision",
            message=f"decision={decision} is not queued for refinement",
        )

    try:
        slice_path = _resolve_slice_path(feedback_path, feedback)
    except ValueError as exc:
        return FeedbackRefineResult(
            feedback_path=str(feedback_path),
            decision=decision,
            status="missing_slice",
            message=str(exc),
        )

    instruction = _read_edit_instruction(_edit_path_for(slice_path))
    source_path = _resolve_source_path(feedback, instruction, slice_path)
    selected_range = _select_refine_range(
        feedback,
        instruction,
        slice_path,
        source_path,
    )
    if selected_range is None:
        return FeedbackRefineResult(
            feedback_path=str(feedback_path),
            decision=decision,
            status="missing_range",
            message="manual_range, context_window, and slice duration are unavailable",
        )

    refined_clip = _refined_clip_path(slice_path, source_path, selected_range)
    edit_json = _edit_path_for(refined_clip)
    title = _select_upload_title(instruction, slice_path)

    try:
        _write_refined_clip(selected_range, refined_clip, title)
        refined_instruction = _build_refined_instruction(
            instruction=instruction,
            source_path=source_path,
            refined_clip=refined_clip,
            selected_range=selected_range,
            title=title,
            feedback=feedback,
        )
        refined_instruction.to_json_file(edit_json)
    except Exception as exc:
        scan_log.error(f"Failed to refine feedback {feedback_path}: {exc}")
        return FeedbackRefineResult(
            feedback_path=str(feedback_path),
            decision=decision,
            status="refine_failed",
            refined_clip=str(refined_clip),
            edit_json=str(edit_json),
            message=str(exc),
        )

    queued = False
    upload_status = "refined"
    if enqueue_upload:
        queued = insert_upload_queue(str(refined_clip))
        upload_status = "queued" if queued else "queue_failed"

    feedback.update(
        {
            "decision": decision,
            "refined": True,
            "generated_refined_clip": str(refined_clip),
            "generated_refined_edit_json": str(edit_json),
            "refined_range": {
                "start": selected_range.source_start,
                "end": selected_range.source_end,
                "relative_to": "source",
            },
            "upload_status": upload_status,
        }
    )
    _write_json(feedback_path, feedback)

    return FeedbackRefineResult(
        feedback_path=str(feedback_path),
        decision=decision,
        status=upload_status,
        refined_clip=str(refined_clip),
        edit_json=str(edit_json),
        queued=queued,
    )


def _select_refine_range(
    feedback: dict[str, Any],
    instruction: EditInstruction | None,
    slice_path: Path,
    source_path: Path,
    ) -> RefineRange | None:
    manual = _valid_manual_range(feedback.get("manual_range"))
    slice_start = infer_slice_start_seconds(str(slice_path))
    source_exists = _has_distinct_source(source_path, slice_path)

    if manual is not None:
        manual_start, manual_end = manual
        duration = manual_end - manual_start
        source_start = slice_start + manual_start
        input_start = source_start if source_exists else manual_start
        return RefineRange(
            input_path=source_path if source_exists else slice_path,
            input_start=input_start,
            source_start=source_start,
            source_end=source_start + duration,
            duration=duration,
            reason=(
                f"dashboard manual_range "
                f"{manual_start:.1f}-{manual_end:.1f} seconds"
            ),
        )

    context_window = _valid_time_range(feedback.get("context_window"))
    if context_window is None and instruction is not None:
        context_window = _valid_time_range(instruction.context_window.to_dict())

    if context_window is not None:
        start, end = context_window
        duration = end - start
        input_start = start if source_exists else max(0.0, start - slice_start)
        return RefineRange(
            input_path=source_path if source_exists else slice_path,
            input_start=input_start,
            source_start=start,
            source_end=end,
            duration=duration,
            reason=f"dashboard context_window {start:.1f}-{end:.1f} seconds",
        )

    duration = _probe_media_duration(slice_path)
    if duration is None or duration <= 0:
        return None
    return RefineRange(
        input_path=slice_path,
        input_start=0.0,
        source_start=slice_start,
        source_end=slice_start + duration,
        duration=duration,
        reason="dashboard keep feedback with full candidate range",
    )


def _write_refined_clip(
    selected_range: RefineRange,
    output_path: Path,
    title: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        _format_seconds(selected_range.input_start),
        "-i",
        str(selected_range.input_path),
        "-t",
        _format_seconds(selected_range.duration),
        "-metadata:g",
        f"generate={title}",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _build_refined_instruction(
    instruction: EditInstruction | None,
    source_path: Path,
    refined_clip: Path,
    selected_range: RefineRange,
    title: str,
    feedback: dict[str, Any],
) -> EditInstruction:
    if instruction is None:
        instruction = EditInstruction(
            source_video=str(source_path),
            slice_video=str(refined_clip),
            decision="keep",
        )

    instruction.source_video = str(source_path)
    instruction.slice_video = str(refined_clip)
    instruction.decision = "keep"
    instruction.trim = TrimInstruction(
        start=0.0,
        end=float(selected_range.duration),
        reason=selected_range.reason,
    )
    instruction.context_window = TimeRange(
        start=selected_range.source_start,
        end=selected_range.source_end,
    )

    density_core = _valid_time_range(feedback.get("density_core"))
    if density_core is not None:
        instruction.density_core = TimeRange(start=density_core[0], end=density_core[1])

    if not instruction.upload_suggestion.title:
        instruction.upload_suggestion.title = title

    action = f"Refined after dashboard keep feedback: {selected_range.reason}"
    if action not in instruction.edit_actions:
        instruction.edit_actions.append(action)
    return instruction


def _resolve_slice_path(feedback_path: Path, feedback: dict[str, Any]) -> Path:
    raw_path = str(feedback.get("slice_path", "")).strip()
    if raw_path:
        path = Path(raw_path)
        if path.is_file():
            return path

    stem = feedback_path.name.removesuffix("_feedback.json")
    for suffix in [".flv", ".mp4"]:
        candidate = feedback_path.with_name(f"{stem}{suffix}")
        if candidate.is_file():
            return candidate
    raise ValueError(f"Cannot resolve slice file for {feedback_path}")


def _resolve_source_path(
    feedback: dict[str, Any],
    instruction: EditInstruction | None,
    slice_path: Path,
) -> Path:
    for value in [
        feedback.get("source_recording"),
        instruction.source_video if instruction is not None else "",
    ]:
        if value:
            path = Path(str(value))
            if path.is_file():
                return path
    return slice_path


def _read_edit_instruction(path: Path) -> EditInstruction | None:
    if not path.is_file():
        return None
    try:
        return EditInstruction.from_json_file(path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        scan_log.warning(f"Failed to read edit instruction {path}: {exc}")
        return None


def _edit_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_edit.json")


def _refined_clip_path(
    slice_path: Path,
    source_path: Path,
    selected_range: RefineRange,
) -> Path:
    if _has_distinct_source(source_path, slice_path):
        source_stem = source_path.stem
    else:
        source_stem = _strip_slice_prefix(slice_path.stem)
    output_stem = (
        f"{_format_seconds(selected_range.source_start)}s_"
        f"{source_stem}_refined"
    )
    return slice_path.with_name(f"{output_stem}.flv")


def _has_distinct_source(source_path: Path, slice_path: Path) -> bool:
    if not source_path.is_file():
        return False
    try:
        return source_path.resolve() != slice_path.resolve()
    except OSError:
        return source_path != slice_path


def _strip_slice_prefix(stem: str) -> str:
    parts = stem.split("s_", 1)
    if len(parts) == 2 and parts[0].replace(".", "", 1).isdigit():
        return parts[1]
    return stem


def _select_upload_title(
    instruction: EditInstruction | None,
    slice_path: Path,
) -> str:
    if instruction is not None and instruction.upload_suggestion.title.strip():
        return instruction.upload_suggestion.title.strip()

    title = _read_generate_metadata(slice_path)
    if title:
        return title
    return slice_path.stem


def _read_generate_metadata(path: Path) -> str:
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            stderr=subprocess.STDOUT,
        ).decode("utf-8")
        data = json.loads(output)
    except Exception:
        return ""
    return str(data.get("format", {}).get("tags", {}).get("generate", "")).strip()


def _probe_media_duration(path: Path) -> float | None:
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stderr=subprocess.STDOUT,
        ).decode("utf-8")
        return float(output.strip())
    except Exception:
        return None


def _normalize_decision(value: Any) -> str:
    decision = str(value or "review")
    return decision if decision in VALID_DECISIONS else "review"


def _valid_manual_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    if value.get("relative_to", "slice") != "slice":
        return None
    start = _as_float(value.get("start"))
    end = _as_float(value.get("end"))
    if start is None or end is None or start < 0 or end <= start:
        return None
    return start, end


def _valid_time_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    start = _as_float(value.get("start"))
    end = _as_float(value.get("end"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_seconds(value: float) -> str:
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_videos_root() -> Path:
    return Path(os.environ.get("BILIVE_VIDEOS_DIR", "Videos")).resolve()


def _print_results(results: Iterable[FeedbackRefineResult]) -> None:
    for result in results:
        suffix = f" -> {result.refined_clip}" if result.refined_clip else ""
        print(f"{result.status}: {result.feedback_path}{suffix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refine dashboard keep feedback and enqueue upload candidates."
    )
    parser.add_argument(
        "videos_root",
        nargs="?",
        default=str(_default_videos_root()),
        help="Videos root to scan, defaults to BILIVE_VIDEOS_DIR or ./Videos.",
    )
    parser.add_argument(
        "--no-queue",
        action="store_true",
        help="Write refined clips/edit JSON without inserting upload_queue rows.",
    )
    args = parser.parse_args(argv)

    results = process_feedback_directory(
        args.videos_root,
        enqueue_upload=not args.no_queue,
    )
    _print_results(results)
    return 1 if any(result.status == "refine_failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
