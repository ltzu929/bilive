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


def _subtitle_filter(srt_path: Path, font_size: int = 20, margin_v: int = 60) -> str:
    return (
        f"subtitles='{_escape_subtitles_path(srt_path)}':"
        f"force_style='Fontsize={font_size},MarginV={margin_v}'"
    )


def burn_subtitles_from_analysis(
    video_path: str | Path,
    analysis: AnalysisResult,
    *,
    font_size: int = 20,
    margin_v: int = 60,
    run=subprocess.run,
    probe_duration: Callable[[Path], float | None] | None = None,
    allow_plain_transcript_fallback: bool = False,
) -> BurnSubtitleResult:
    video_path = Path(video_path)
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
            video_path=str(video_path),
            message="no valid timestamped transcript segments",
        )

    srt_path = video_path.with_name(f"{video_path.stem}_asr.srt")
    temp_output = video_path.with_name(
        f"{video_path.stem}_subtitled.tmp{video_path.suffix}"
    )
    try:
        srt_path.write_text(srt_text, encoding="utf-8")
        command = _burn_command(
            video_path,
            temp_output,
            srt_path,
            analysis,
            font_size=font_size,
            margin_v=margin_v,
        )
        run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        os.replace(temp_output, video_path)
        scan_log.info(f"Burned ASR subtitles into slice: {video_path}")
        return BurnSubtitleResult(
            burned=True,
            video_path=str(video_path),
            srt_path=str(srt_path),
            message="subtitles burned",
        )
    except Exception as exc:
        if temp_output.exists():
            temp_output.unlink()
        scan_log.warning(f"Failed to burn ASR subtitles for {video_path}: {exc}")
        return BurnSubtitleResult(
            burned=False,
            video_path=str(video_path),
            srt_path=str(srt_path),
            message=str(exc),
        )


def _burn_command(
    video_path: Path,
    temp_output: Path,
    srt_path: Path,
    analysis: AnalysisResult,
    *,
    font_size: int,
    margin_v: int,
) -> list[str]:
    subtitle_filter = _subtitle_filter(srt_path, font_size=font_size, margin_v=margin_v)
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
