# Copyright (c) 2024 bilive.
"""Media streaming routes: bounded range requests for source recordings + previews."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from src.dashboard._context import DashboardContext, get_context


router = APIRouter()

CHUNK_SIZE = 1024 * 1024


def _iter_file_range(path: Path, start: int, end: int):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _media_response(
    path: Path,
    request: Request,
    media_type: str | None = None,
) -> Response:
    file_size = path.stat().st_size
    response_media_type = media_type or mimetypes.guess_type(path.name)[0]
    response_media_type = response_media_type or "application/octet-stream"
    range_header = request.headers.get("range")
    common_headers = {"Accept-Ranges": "bytes"}

    if not range_header:
        return FileResponse(
            path,
            media_type=response_media_type,
            headers=common_headers,
        )

    # Parse the range locally — kept inline so this module is self-contained for
    # streaming concerns and avoids re-exporting media_response through helpers.
    start_text, separator, end_text = "", "", ""
    if range_header.startswith("bytes=") and "," not in range_header:
        start_text, separator, end_text = range_header[6:].partition("-")

    def _bad_range() -> Response:
        return Response(
            status_code=416,
            headers={
                **common_headers,
                "Content-Range": f"bytes */{file_size}",
            },
        )

    if not separator:
        return _bad_range()

    try:
        if start_text == "":
            suffix_size = int(end_text)
            if suffix_size <= 0:
                raise ValueError
            start = max(file_size - suffix_size, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        if start < 0 or start >= file_size or end < start:
            raise ValueError
    except (TypeError, ValueError):
        return _bad_range()

    end = min(end, file_size - 1)
    content_length = end - start + 1
    headers = {
        **common_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(
        _iter_file_range(path, start, end),
        status_code=206,
        media_type=response_media_type,
        headers=headers,
    )


@router.get("/api/media/{media_id}")
async def get_media(
    media_id: str,
    request: Request,
    ctx: DashboardContext = Depends(get_context),
) -> Response:
    try:
        path = ctx.store.resolve_media(media_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _media_response(path, request)


@router.get("/api/preview/{media_id}")
async def get_preview(
    media_id: str,
    request: Request,
    ctx: DashboardContext = Depends(get_context),
) -> Response:
    try:
        path = ctx.store.resolve_preview_media(media_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _media_response(path, request, media_type="video/mp4")