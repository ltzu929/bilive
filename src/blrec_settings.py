"""Harden blrec settings so source FLV files survive until PC-side validation."""

from __future__ import annotations

import argparse
import os
import shutil
import tomllib
from pathlib import Path


def keep_source_flv(settings_path: Path) -> bool:
    """Set postprocessing.delete_source to never without rewriting unrelated TOML."""
    settings_path = Path(settings_path)
    original = settings_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    section = ""
    changed = False
    found = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section != "[postprocessing]" or not stripped.startswith("delete_source"):
            continue

        key, separator, _ = stripped.partition("=")
        if not separator or key.strip() != "delete_source":
            continue
        found = True
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        replacement = f'delete_source = "never"{ending}'
        if line != replacement:
            lines[index] = replacement
            changed = True
        break

    if not found:
        raise ValueError("missing [postprocessing] delete_source setting")
    if not changed:
        return False

    updated = "".join(lines)
    parsed = tomllib.loads(updated)
    if parsed.get("postprocessing", {}).get("delete_source") != "never":
        raise ValueError("failed to set [postprocessing] delete_source=never")

    backup = settings_path.with_suffix(
        settings_path.suffix + ".before-bilive-hardening"
    )
    if not backup.exists():
        shutil.copy2(settings_path, backup)

    temporary = settings_path.with_suffix(settings_path.suffix + ".bilive-tmp")
    temporary.write_text(updated, encoding="utf-8", newline="")
    os.replace(temporary, settings_path)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "settings",
        nargs="?",
        type=Path,
        default=Path("/mnt/win/bilive/settings.toml"),
    )
    args = parser.parse_args(argv)
    changed = keep_source_flv(args.settings)
    print(
        f"blrec source retention: {'enabled' if changed else 'already enabled'} "
        f"({args.settings})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
