# Copyright (c) 2024 bilive.
"""Bilibili cookie parsing for the upload consumer."""

from __future__ import annotations

from pathlib import Path


def parse_cookie_file(path: str | Path) -> dict[str, str]:
    cookie_path = Path(path)
    text = cookie_path.read_text(encoding="utf-8").strip()
    cookies: dict[str, str] = {}
    for item in text.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key:
            cookies[key.strip()] = value.strip()
    missing = [name for name in ("SESSDATA", "bili_jct") if not cookies.get(name)]
    if missing:
        raise ValueError(f"missing Bilibili cookies: {', '.join(missing)}")
    return cookies