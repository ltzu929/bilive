# Copyright (c) 2024 bilive.
"""Poll published slices for their latest Bilibili performance (Windows side).

For every ``upload_queue`` row that reached ``status='published'`` with a
non-empty ``bvid``, this module fetches the public view stats and upserts the
latest snapshot into ``slice_performance``. It is read-only against Bilibili
(the public ``x/web-interface/view`` endpoint) and rate-limits requests to
avoid风控. The fetcher is injectable so tests never hit the network.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import requests

from src.db.conn import (
    list_upload_queue,
    migrate_slice_performance,
    upsert_slice_performance,
)
from src.upload.cookie import parse_cookie_file


VIEW_API = "https://api.bilibili.com/x/web-interface/view"

# slice_performance column -> Bilibili ``data.stat`` key
STAT_FIELD_MAP = {
    "view": "view",
    "likes": "like",
    "coin": "coin",
    "favorite": "favorite",
    "share": "share",
    "reply": "reply",
    "danmaku": "danmaku",
}

StatsFetcher = Callable[[str], "dict[str, Any] | None"]


def _default_cookie_file() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / ".secrets" / "bilibili.cookie"


def _build_session(cookie_file: str | Path | None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/143.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }
    )
    path = Path(cookie_file) if cookie_file else _default_cookie_file()
    if path.is_file():
        try:
            session.cookies.update(parse_cookie_file(path))
        except (OSError, ValueError):
            # Public view endpoint works without cookies; auth only sharpens
            # visibility of a few fields, so a missing/invalid cookie is fine.
            pass
    return session


def fetch_video_stats(
    bvid: str,
    *,
    session: requests.Session,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Fetch and map public view stats for ``bvid``.

    Returns a dict keyed by ``slice_performance`` columns, or ``None`` when the
    response is malformed or the API reports a non-zero code.
    """
    response = session.get(VIEW_API, params={"bvid": bvid}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    stat = data.get("stat")
    if not isinstance(stat, dict):
        return None
    mapped = {
        column: stat[source]
        for column, source in STAT_FIELD_MAP.items()
        if stat.get(source) is not None
    }
    return mapped or None


def refresh_published_stats(
    *,
    db_path: str | Path | None = None,
    cookie_file: str | Path | None = None,
    fetcher: StatsFetcher | None = None,
    rate_limit_seconds: float = 1.0,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Refresh ``slice_performance`` stats for every published slice.

    Returns a summary ``{"total", "updated", "failed"}``. Individual fetch
    failures are isolated so one bad bvid never aborts the batch.
    """
    migrate_slice_performance(db_path)

    published = [
        row
        for row in list_upload_queue(db_path)
        if row.get("status") == "published" and str(row.get("bvid") or "").strip()
    ]

    session: requests.Session | None = None
    if fetcher is None:
        session = _build_session(cookie_file)

        def fetcher(bvid: str) -> dict[str, Any] | None:
            return fetch_video_stats(bvid, session=session)

    summary = {"total": len(published), "updated": 0, "failed": 0}
    for index, row in enumerate(published):
        bvid = str(row["bvid"]).strip()
        try:
            stats = fetcher(bvid)
        except Exception:
            summary["failed"] += 1
            stats = None
        if stats:
            snapshot = dict(stats)
            snapshot["collected_at"] = now()
            if upsert_slice_performance(bvid, snapshot, db_path=db_path):
                summary["updated"] += 1
            else:
                summary["failed"] += 1
        if rate_limit_seconds > 0 and index + 1 < len(published):
            sleep(rate_limit_seconds)

    return summary
