"""Install the repository-maintained blrec FPS guard."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
from pathlib import Path


EXPECTED_BLREC_VERSION = "2.0.0b4"
ORIGINAL_SOURCE_SHA256 = (
    "a00f9e5d95483d50f68f1ed4dbe60193f2930181a29e1b402ceade3e8e07843f"
)
PATCHED_SOURCE_SHA256 = (
    "0cec9cc4a006a21d4c69848ef6a19406ec4dda050e6b1b0f093797b347eec07a"
)


class PatchError(RuntimeError):
    """Raised when the installed blrec source is not the expected build."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _patched_source(original: bytes) -> bytes:
    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"

    import_anchor = f"from loguru import logger{newline}"
    import_replacement = (
        f"from loguru import logger{newline}{newline}"
        f"from src.blrec_compat import normalize_frame_rate{newline}"
    )
    parameter_block = newline.join(
        [
            "                fps = metadata.get('fps') or metadata.get('framerate')",
            "",
            "                if not fps:",
            "                    return",
            "",
            "                frame_rate = fps",
            "                video_frame_interval = math.ceil(1000 / frame_rate)",
        ]
    ) + newline
    patched_block = newline.join(
        [
            "                fps = metadata.get('fps') or metadata.get('framerate')",
            "                frame_rate = normalize_frame_rate(fps)",
            "                video_frame_interval = math.ceil(1000 / frame_rate)",
        ]
    ) + newline

    if text.count(import_anchor) != 1 or text.count(parameter_block) != 1:
        raise PatchError("expected blrec FPS source anchors were not found")

    text = text.replace(import_anchor, import_replacement, 1)
    text = text.replace(parameter_block, patched_block, 1)
    return text.encode("utf-8")


def patch_blrec_source(source_path: Path, installed_version: str) -> bool:
    """Patch a known blrec source file and return whether it changed."""
    if installed_version != EXPECTED_BLREC_VERSION:
        raise PatchError(
            f"unsupported blrec version {installed_version!r}; "
            f"expected {EXPECTED_BLREC_VERSION!r}"
        )

    source_path = Path(source_path)
    current = source_path.read_bytes()
    current_hash = _sha256(current)
    if current_hash == PATCHED_SOURCE_SHA256:
        return False
    if current_hash != ORIGINAL_SOURCE_SHA256:
        raise PatchError(
            f"unexpected blrec fix.py hash {current_hash}; refusing to patch"
        )

    patched = _patched_source(current)
    patched_hash = _sha256(patched)
    if patched_hash != PATCHED_SOURCE_SHA256:
        raise PatchError(
            f"generated blrec patch hash {patched_hash} does not match expected hash"
        )
    compile(patched, str(source_path), "exec")

    backup = source_path.with_suffix(source_path.suffix + ".before-bilive-fps-guard")
    if not backup.exists():
        shutil.copy2(source_path, backup)

    temporary = source_path.with_suffix(source_path.suffix + ".bilive-tmp")
    temporary.write_bytes(patched)
    os.chmod(temporary, source_path.stat().st_mode)
    os.replace(temporary, source_path)
    return True


def _installed_fix_path() -> Path:
    spec = importlib.util.find_spec("blrec.flv.operators.fix")
    if spec is None or spec.origin is None:
        raise PatchError("cannot locate installed blrec.flv.operators.fix")
    return Path(spec.origin)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, help="override fix.py path for diagnostics")
    parser.add_argument("--version", help="override detected version for diagnostics")
    args = parser.parse_args(argv)

    version = args.version or importlib.metadata.version("blrec")
    target = args.target or _installed_fix_path()
    changed = patch_blrec_source(target, version)
    print(f"blrec FPS guard: {'installed' if changed else 'already installed'} ({target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
