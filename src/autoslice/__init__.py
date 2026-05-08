# Copyright (c) 2024 bilive.

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from .danmaku_slice import GeneratedSlice, slice_video_by_danmaku
from .analysis_result import AnalysisResult, Highlight, TranscriptSegment, TrimSuggestion
from .slice_quality_filter import should_retain_slice
from .edit_instruction import (
    DanmakuEvidence,
    EditInstruction,
    EditSegment,
    SubtitleEvidence,
    TimeRange,
    TrimInstruction,
    UploadSuggestion,
)
from .edit_instruction_builder import (
    build_and_write_edit_instruction,
    build_edit_instruction,
)
from .prompt_packager import build_prompt_markdown, write_prompt_package

__all__ = [
    "slice_video_by_danmaku",
    "GeneratedSlice",
    "AnalysisResult",
    "Highlight",
    "TranscriptSegment",
    "TrimSuggestion",
    "should_retain_slice",
    "DanmakuEvidence",
    "EditInstruction",
    "EditSegment",
    "SubtitleEvidence",
    "TimeRange",
    "TrimInstruction",
    "UploadSuggestion",
    "build_edit_instruction",
    "build_and_write_edit_instruction",
    "build_prompt_markdown",
    "write_prompt_package",
]
