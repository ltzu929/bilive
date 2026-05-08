# Copyright (c) 2024 bilive.

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.dashboard.schemas import VALID_DECISIONS, RoomItem, SliceItem


SLICE_NAME_RE = re.compile(r"^(?P<start>\d+(?:\.\d+)?)s_(?P<source>.+)\.(mp4|flv)$")


class DashboardFileStore:
    def __init__(self, videos_root: str | Path) -> None:
        self.videos_root = Path(videos_root).resolve()

    def list_rooms(self) -> List[RoomItem]:
        if not self.videos_root.is_dir():
            return []
        rooms = [
            RoomItem(room_id=path.name)
            for path in self.videos_root.iterdir()
            if path.is_dir() and path.name.isdigit()
        ]
        return sorted(rooms, key=lambda room: room.room_id)

    def list_slices(self, room_id: str | None = None) -> List[SliceItem]:
        rooms: Iterable[Path]
        if room_id:
            rooms = [self._safe_room_dir(room_id)]
        else:
            rooms = [
                self.videos_root / room.room_id
                for room in self.list_rooms()
            ]

        items: List[SliceItem] = []
        for room_dir in rooms:
            if not room_dir.is_dir():
                continue
            for path in sorted(room_dir.iterdir(), key=lambda item: item.name):
                if not path.is_file() or not SLICE_NAME_RE.match(path.name):
                    continue
                try:
                    items.append(self._build_slice_item(path))
                except ValueError:
                    continue
        return items

    def read_feedback(self, slice_id: str) -> Dict[str, Any]:
        item = self.get_slice(slice_id)
        feedback_path = Path(item.feedback_path)
        if not feedback_path.is_file():
            return self._default_feedback(item)
        try:
            data = json.loads(feedback_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._default_feedback(item)
        return self._normalize_feedback(item, data)

    def write_feedback(self, slice_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        item = self.get_slice(slice_id)
        feedback = self._normalize_feedback(item, data)
        Path(item.feedback_path).write_text(
            json.dumps(feedback, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return feedback

    def resolve_media(self, media_id: str) -> Path:
        path = self._decode_id(media_id)
        if not path.is_file() or not SLICE_NAME_RE.match(path.name):
            raise ValueError("Unknown media id")
        return path

    def resolve_preview_media(self, media_id: str) -> Path:
        path = self.resolve_media(media_id)
        if path.suffix.lower() == ".mp4":
            return path
        if path.suffix.lower() != ".flv":
            raise ValueError("Unsupported preview media")
        return self._ensure_mp4_preview(path)

    def get_slice(self, slice_id: str) -> SliceItem:
        path = self._decode_id(slice_id)
        if not path.is_file() or not SLICE_NAME_RE.match(path.name):
            raise ValueError("Unknown slice id")
        return self._build_slice_item(path)

    def _build_slice_item(self, path: Path) -> SliceItem:
        path = self._ensure_under_root(path.resolve())
        match = SLICE_NAME_RE.match(path.name)
        if not match:
            raise ValueError("Not a generated slice")

        feedback_path = path.with_name(f"{path.stem}_feedback.json")
        source_recording = path.with_name(match.group("source") + ".mp4")
        if not source_recording.exists():
            source_recording = path.with_name(match.group("source") + path.suffix)

        item = SliceItem(
            id=self._encode_path(path),
            media_id=self._encode_path(path),
            room_id=path.parent.name,
            name=path.name,
            path=str(path),
            source_recording=str(source_recording),
            feedback_path=str(feedback_path),
            size_bytes=path.stat().st_size,
        )
        feedback = self._read_feedback_file(item) if feedback_path.is_file() else {}
        if feedback:
            item.decision = feedback.get("decision", item.decision)
            item.quality_reason = feedback.get("quality_reason", "")
            item.manual_range = feedback.get("manual_range", item.manual_range)
            item.density_core = feedback.get("density_core")
            item.context_window = feedback.get("context_window")
            item.danmaku_count = feedback.get("danmaku_count")
        return item

    def _read_feedback_file(self, item: SliceItem) -> Dict[str, Any]:
        feedback_path = Path(item.feedback_path)
        try:
            data = json.loads(feedback_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self._default_feedback(item)
        return self._normalize_feedback(item, data)

    def _default_feedback(self, item: SliceItem) -> Dict[str, Any]:
        return {
            "slice_path": item.path,
            "source_recording": item.source_recording,
            "room_id": item.room_id,
            "decision": "review",
            "quality_reason": "",
            "manual_range": {"start": 0.0, "end": 0.0, "relative_to": "slice"},
            "density_core": None,
            "context_window": None,
        }

    def _normalize_feedback(
        self, item: SliceItem, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        feedback = self._default_feedback(item)
        decision = str(data.get("decision", feedback["decision"]))
        if decision not in VALID_DECISIONS:
            decision = "review"
        feedback["decision"] = decision
        feedback["quality_reason"] = str(data.get("quality_reason", ""))
        feedback["manual_range"] = self._normalize_manual_range(
            data.get("manual_range", feedback["manual_range"])
        )
        for key in ["density_core", "context_window", "danmaku_count"]:
            if key in data:
                feedback[key] = data[key]
        return feedback

    def _normalize_manual_range(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        return {
            "start": self._as_float(value.get("start", 0.0)),
            "end": self._as_float(value.get("end", 0.0)),
            "relative_to": "slice",
        }

    def _safe_room_dir(self, room_id: str) -> Path:
        if not re.match(r"^\d+$", str(room_id)):
            raise ValueError("Invalid room id")
        return self._ensure_under_root(self.videos_root / str(room_id))

    def _encode_path(self, path: Path) -> str:
        relative = path.relative_to(self.videos_root).as_posix()
        return base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii")

    def _decode_id(self, value: str) -> Path:
        try:
            relative = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise ValueError("Invalid id") from exc
        return self._ensure_under_root((self.videos_root / relative).resolve())

    def _ensure_mp4_preview(self, path: Path) -> Path:
        relative = path.relative_to(self.videos_root).as_posix()
        cache_name = base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii")
        cache_root = self.videos_root / ".dashboard-cache" / "previews"
        output_path = cache_root / f"{cache_name}.mp4"

        if output_path.is_file() and output_path.stat().st_mtime >= path.stat().st_mtime:
            return output_path

        cache_root.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(".tmp.mp4")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    path,
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    temp_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            temp_path.replace(output_path)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise ValueError("Unable to prepare preview media") from exc
        return output_path

    def _ensure_under_root(self, path: Path) -> Path:
        path = path.resolve()
        try:
            path.relative_to(self.videos_root)
        except ValueError as exc:
            raise ValueError("Path is outside Videos root") from exc
        return path

    def _as_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
