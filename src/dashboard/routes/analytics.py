# Copyright (c) 2024 bilive.
"""Read-only slice performance panel route.

Serves the ``slice_performance`` snapshot (feature + post-publish stats) for the
dashboard. This route MUST stay read-only: it never triggers the
``slice_performance`` migration. When the table is absent (e.g. no publish has
happened yet, or the DB lives only on the Windows worker), it returns
``{"status": "unavailable"}`` instead of creating anything.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter


router = APIRouter()


@router.get("/api/slice-performance")
async def get_slice_performance_panel() -> Dict[str, Any]:
    from src.db import conn

    if not conn.slice_performance_available():
        return {"status": "unavailable", "items": []}
    return {"status": "ok", "items": conn.get_slice_performance()}
