# Copyright (c) 2024 bilive.

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


VALID_DECISIONS = {"keep", "drop", "review"}


@dataclass
class SliceItem:
    id: str
    media_id: str
    room_id: str
    name: str
    path: str
    source_recording: str
    feedback_path: str
    size_bytes: int = 0
    decision: str = "review"
    quality_reason: str = ""
    manual_range: Dict[str, Any] = field(
        default_factory=lambda: {"start": 0.0, "end": 0.0, "relative_to": "slice"}
    )
    density_core: Optional[Dict[str, Any]] = None
    context_window: Optional[Dict[str, Any]] = None
    danmaku_count: Optional[int] = None
    refined: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RoomItem:
    room_id: str

    def to_dict(self) -> Dict[str, str]:
        return {"room_id": self.room_id}
