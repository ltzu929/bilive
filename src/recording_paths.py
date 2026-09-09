"""Recorder directory and source filename conventions shared by readers."""

import re
from pathlib import Path


ROOM_DIR_RE = re.compile(r"^(\d+)(?: - (.+))?$")
SOURCE_NAME_RE = re.compile(
    r"^(?:\d+_\d{8}-\d{2}-\d{2}-\d{2}|"
    r"blive_\d+_\d{4}-\d{2}-\d{2}-\d{6})(?:_\(\d+\))?\.mp4$"
)


def room_identity(path: Path) -> tuple[str, str]:
    match = ROOM_DIR_RE.fullmatch(path.name)
    if not match:
        return "", ""
    return match[1], match[2] or match[1]


def room_directories(root: Path, room_id: str | None = None) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.iterdir()
         if path.is_dir() and room_identity(path)[0]
         and (room_id is None or room_identity(path)[0] == room_id)),
        key=lambda path: path.name,
    )


def source_recordings(room: Path) -> list[Path]:
    return sorted(
        (path for path in room.iterdir()
         if path.is_file() and SOURCE_NAME_RE.fullmatch(path.name)),
        key=lambda path: path.name,
    )
