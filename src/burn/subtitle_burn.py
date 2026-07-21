from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
from typing import Callable, Iterable

from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
from src.log.logger import scan_log


@dataclass
class BurnSubtitleResult:
    burned: bool
    video_path: str
    srt_path: str | None = None
    message: str = ""


def _format_style_number(value: float) -> str:
    """Render a style number without trailing zeros (2.0 -> '2', 1.5 -> '1.5')."""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class SubtitleStyle:
    """Configurable burned-subtitle appearance.

    Only ``font_size`` and ``margin_v`` are emitted by default so the produced
    ``force_style`` string stays byte-equivalent to the historical
    ``Fontsize=20,MarginV=60``. Optional fields are omitted from the filter
    when unset.
    """

    font_size: int = 20
    margin_v: int = 60
    alignment: int | None = None      # ASS numpad alignment (1-9)
    outline: float | None = None      # outline (描边) width
    primary_colour: str | None = None  # ASS &HAABBGGRR
    outline_colour: str | None = None  # ASS &HAABBGGRR

    def to_force_style(self) -> str:
        parts = [f"Fontsize={int(self.font_size)}", f"MarginV={int(self.margin_v)}"]
        if self.alignment is not None:
            parts.append(f"Alignment={int(self.alignment)}")
        if self.outline is not None:
            parts.append(f"Outline={_format_style_number(self.outline)}")
        if self.primary_colour:
            parts.append(f"PrimaryColour={self.primary_colour}")
        if self.outline_colour:
            parts.append(f"OutlineColour={self.outline_colour}")
        return ",".join(parts)

    @classmethod
    def from_mapping(cls, data: dict | None) -> "SubtitleStyle":
        """Build a style from a plain mapping, ignoring unknown/blank fields."""
        base = cls()
        if not isinstance(data, dict):
            return base

        def _int(key, default):
            value = data.get(key)
            try:
                return int(value) if value is not None and value != "" else default
            except (TypeError, ValueError):
                return default

        def _opt_int(key):
            value = data.get(key)
            try:
                return int(value) if value is not None and value != "" else None
            except (TypeError, ValueError):
                return None

        def _opt_float(key):
            value = data.get(key)
            try:
                return float(value) if value is not None and value != "" else None
            except (TypeError, ValueError):
                return None

        def _opt_str(key):
            value = data.get(key)
            text = str(value).strip() if value is not None else ""
            return text or None

        return cls(
            font_size=_int("font_size", base.font_size),
            margin_v=_int("margin_v", base.margin_v),
            alignment=_opt_int("alignment"),
            outline=_opt_float("outline"),
            primary_colour=_opt_str("primary_colour"),
            outline_colour=_opt_str("outline_colour"),
        )

    def to_mapping(self) -> dict:
        """Serialise non-default fields for persistence in task metadata."""
        data: dict = {"font_size": int(self.font_size), "margin_v": int(self.margin_v)}
        if self.alignment is not None:
            data["alignment"] = int(self.alignment)
        if self.outline is not None:
            data["outline"] = float(self.outline)
        if self.primary_colour:
            data["primary_colour"] = self.primary_colour
        if self.outline_colour:
            data["outline_colour"] = self.outline_colour
        return data


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def segments_to_srt(segments: Iterable[TranscriptSegment]) -> str:
    blocks: list[str] = []
    index = 1
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(segment.start))
        end = float(segment.end)
        if end <= start:
            continue
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n"
            f"{text}\n"
        )
        index += 1
    if not blocks:
        return ""
    return "\n".join(blocks)


def transcript_to_segments(
    transcript: str,
    duration_seconds: float,
    *,
    max_chars: int = 14,
    max_duration: float = 3.0,
) -> list[TranscriptSegment]:
    text = " ".join(str(transcript or "").split())
    if not text:
        return []

    phrases = [
        match.group(0).strip()
        for match in re.finditer(
            r"[^,，、;；:：.!?\u3002\uff01\uff1f]+[,，、;；:：.!?\u3002\uff01\uff1f]*",
            text,
        )
        if match.group(0).strip()
    ]
    chunks: list[str] = []
    for phrase in phrases or [text]:
        while len(phrase) > max_chars:
            cut = max_chars
            while cut < len(phrase) and phrase[cut] in ",，、;；:：.!?\u3002\uff01\uff1f":
                cut += 1
            chunk = phrase[:cut].strip()
            if chunk:
                chunks.append(chunk)
            phrase = phrase[cut:].strip()
        if phrase:
            chunks.append(phrase)

    if not chunks:
        return []

    duration = max(1.0, float(duration_seconds or 0))
    step = min(float(max_duration), duration / len(chunks))
    segments: list[TranscriptSegment] = []
    for index, chunk in enumerate(chunks):
        start = index * step
        end = min(duration, start + step)
        if end <= start:
            break
        segments.append(TranscriptSegment(start=start, end=end, text=chunk))
    return segments


def probe_video_duration(
    video_path: str | Path,
    *,
    run=subprocess.run,
) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        return float(str(result.stdout).strip())
    except Exception as exc:
        scan_log.warning(f"Failed to probe video duration for subtitles: {exc}")
        return None


def _escape_subtitles_path(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return value.replace(":", r"\:").replace("'", r"\'")


def _subtitle_filter(srt_path: Path, style: SubtitleStyle | None = None) -> str:
    style = style or SubtitleStyle()
    return (
        f"subtitles='{_escape_subtitles_path(srt_path)}':"
        f"force_style='{style.to_force_style()}'"
    )


def burn_subtitles_from_analysis(
    video_path: str | Path,
    analysis: AnalysisResult,
    *,
    output_path: str | Path | None = None,
    font_size: int = 20,
    margin_v: int = 60,
    style: SubtitleStyle | None = None,
    run=subprocess.run,
    probe_duration: Callable[[Path], float | None] | None = None,
    allow_plain_transcript_fallback: bool = False,
) -> BurnSubtitleResult:
    if style is None:
        style = SubtitleStyle(font_size=font_size, margin_v=margin_v)
    video_path = Path(video_path)
    final_output = Path(output_path) if output_path is not None else video_path
    srt_text = segments_to_srt(analysis.transcript_segments)
    if not srt_text and allow_plain_transcript_fallback and analysis.transcript:
        duration = (
            probe_duration(video_path)
            if probe_duration is not None
            else probe_video_duration(video_path)
        )
        srt_text = segments_to_srt(
            transcript_to_segments(analysis.transcript, duration or 120.0)
        )
    if not srt_text:
        return BurnSubtitleResult(
            burned=False,
            video_path=str(final_output),
            message="no valid timestamped transcript segments",
        )

    srt_path = video_path.with_name(f"{video_path.stem}_asr.srt")
    temp_output = (
        final_output
        if output_path is not None
        else video_path.with_name(f"{video_path.stem}_subtitled.tmp{video_path.suffix}")
    )
    try:
        srt_path.write_text(srt_text, encoding="utf-8")
        command = _burn_command(
            video_path,
            temp_output,
            srt_path,
            analysis,
            style=style,
        )
        run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        if output_path is None:
            os.replace(temp_output, video_path)
        scan_log.info(f"Burned ASR subtitles into slice: {video_path}")
        return BurnSubtitleResult(
            burned=True,
            video_path=str(final_output),
            srt_path=str(srt_path),
            message="subtitles burned",
        )
    except Exception as exc:
        if temp_output.exists():
            temp_output.unlink()
        scan_log.warning(f"Failed to burn ASR subtitles for {video_path}: {exc}")
        return BurnSubtitleResult(
            burned=False,
            video_path=str(final_output),
            srt_path=str(srt_path),
            message=str(exc),
        )


def _burn_command(
    video_path: Path,
    temp_output: Path,
    srt_path: Path,
    analysis: AnalysisResult,
    *,
    style: SubtitleStyle | None = None,
) -> list[str]:
    subtitle_filter = _subtitle_filter(srt_path, style=style)
    trim = analysis.suggested_trim
    if trim is None:
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:a",
            "copy",
            str(temp_output),
        ]

    start = max(0.0, float(trim.trim_start))
    duration = max(0.0, float(trim.trim_end) - start)
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(temp_output),
    ]
