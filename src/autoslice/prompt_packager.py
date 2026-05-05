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
