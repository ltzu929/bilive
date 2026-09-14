# Copyright (c) 2024 bilive.
"""Lightweight post-ASR transcript correction for proper nouns and homophones.

Fail-soft by design: any API/schema problem keeps the original Whisper text.
Correction never changes timestamps and never invents new cue lines.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from openai import OpenAI

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.config import MIMO_BASE_URL, MIMO_MODEL, MIMO_TIMEOUT
from src.log.logger import scan_log


def _compact_lines(segments: list[TranscriptSegment], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    used = 0
    for index, segment in enumerate(segments):
        text = str(segment.text or "").strip()
        if not text:
            continue
        line = f"{index}\t{text}"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _build_correct_prompt(
    segments: list[TranscriptSegment],
    *,
    artist: str = "",
    title: str = "",
    context: str = "",
) -> str:
    body = _compact_lines(segments)
    context_text = str(context or "").strip()
    if len(context_text) > 800:
        context_text = context_text[:797] + "..."
    return (
        "你是直播字幕校对员。下面 ASR 字幕可能把主播名、游戏名、梗名或同音字听错。\n"
        f"主播: {artist or 'unknown'}\n"
        f"标题线索: {title or '(none)'}\n"
        f"弹幕关键词线索: {context_text or '(none)'}\n\n"
        "只修正专有名词、明显同音错字和专名写法；不要改时间，不要增删行，"
        "不要润色口语，不要把原意改掉。拿不准就不要改。\n"
        "每行格式为「索引\\t原句」。返回严格 JSON：\n"
        '{"corrections":[{"index":0,"text":"修正后整句"}]}\n'
        "无需修改时返回 {\"corrections\":[]}。\n\n"
        "字幕:\n"
        f"{body}"
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def correct_transcript_segments(
    segments: list[TranscriptSegment],
    *,
    artist: str = "",
    title: str = "",
    context: str = "",
    model: str = MIMO_MODEL,
    base_url: str = MIMO_BASE_URL,
    timeout: float = MIMO_TIMEOUT,
    client_factory: Callable[..., Any] = OpenAI,
) -> list[TranscriptSegment]:
    """Return a new segment list with text-only corrections applied."""
    usable = [segment for segment in segments if str(segment.text or "").strip()]
    if not usable:
        return list(segments)

    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        scan_log.warning("Subtitle correction skipped: MIMO_API_KEY is not set")
        return list(segments)

    try:
        client = client_factory(api_key=api_key, base_url=base_url)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是谨慎的直播字幕校对。只修正专名和明显听错，"
                        "输出严格 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": _build_correct_prompt(
                        usable,
                        artist=artist,
                        title=title,
                        context=context,
                    ),
                },
            ],
            max_completion_tokens=2048,
            timeout=timeout,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        if not completion.choices:
            raise ValueError("correction response has no choices")
        content = str(getattr(completion.choices[0].message, "content", "") or "")
        parsed = _extract_json(content)
        if parsed is None:
            raise ValueError("correction JSON parse failed")
        raw_corrections = parsed.get("corrections", [])
        if raw_corrections is None:
            raw_corrections = []
        if not isinstance(raw_corrections, list):
            raise ValueError("corrections must be an array")
    except Exception as exc:
        scan_log.warning(f"Subtitle correction failed; keeping original ASR: {exc}")
        return list(segments)

    # Compact-line indices only cover non-empty rows; map them back to
    # the original ``segments`` list positions.
    usable_indices = [
        index
        for index, segment in enumerate(segments)
        if str(segment.text or "").strip()
    ]
    index_map = {
        compact_index: original_index
        for compact_index, original_index in enumerate(usable_indices)
    }

    corrected = list(segments)
    applied = 0
    for item in raw_corrections:
        if not isinstance(item, dict):
            continue
        try:
            compact_index = int(item.get("index"))
            text = str(item.get("text") or "").strip()
        except (TypeError, ValueError):
            continue
        if not text or compact_index not in index_map:
            continue
        original_index = index_map[compact_index]
        if text != corrected[original_index].text:
            corrected[original_index] = TranscriptSegment(
                start=corrected[original_index].start,
                end=corrected[original_index].end,
                text=text,
            )
            applied += 1

    if applied:
        scan_log.info(f"Subtitle correction applied to {applied} cue(s)")
    return corrected


def correct_analysis_subtitles(
    analysis: AnalysisResult,
    *,
    artist: str = "",
    context: str = "",
    **kwargs: Any,
) -> AnalysisResult:
    """Correct ``analysis.transcript_segments`` in place and return it."""
    if not analysis.transcript_segments:
        return analysis
    analysis.transcript_segments = correct_transcript_segments(
        analysis.transcript_segments,
        artist=artist,
        title=analysis.title,
        context=context,
        **kwargs,
    )
    if analysis.transcript_segments:
        analysis.transcript = " ".join(
            segment.text.strip()
            for segment in analysis.transcript_segments
            if str(segment.text or "").strip()
        ).strip()
    return analysis
