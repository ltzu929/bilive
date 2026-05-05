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
