# Copyright (c) 2024 bilive.

import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.dashboard.file_store import DashboardFileStore
from src.dashboard.slice_control import load_pending_queue_state, start_slice_scan
from src.burn.slice_progress import load_progress_state


CHUNK_SIZE = 1024 * 1024


def default_videos_root() -> Path:
    env_path = os.environ.get("BILIVE_VIDEOS_DIR")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "Videos"


def iter_file_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes=") or "," in range_header:
        raise ValueError("Unsupported range")
    start_text, separator, end_text = range_header[6:].partition("-")
    if not separator:
        raise ValueError("Unsupported range")

    if start_text == "":
        suffix_size = int(end_text)
        if suffix_size <= 0:
            raise ValueError("Invalid range")
        start = max(file_size - suffix_size, 0)
        end = file_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1

    if start < 0 or start >= file_size or end < start:
        raise ValueError("Invalid range")
    return start, min(end, file_size - 1)


def media_response(
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

    try:
        start, end = parse_range_header(range_header, file_size)
    except (TypeError, ValueError):
        return Response(
            status_code=416,
            headers={
                **common_headers,
                "Content-Range": f"bytes */{file_size}",
            },
        )

    content_length = end - start + 1
    headers = {
        **common_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    with path.open("rb") as file:
        file.seek(start)
        content = file.read(content_length)
    return Response(
        content,
        status_code=206,
        media_type=response_media_type,
        headers=headers,
    )


def create_app(
    videos_root: str | Path | None = None,
    static_dir: str | Path | None = None,
    slice_starter=None,
) -> FastAPI:
    app = FastAPI(title="bilive dashboard", version="0.1.0")
    store = DashboardFileStore(videos_root or default_videos_root())
    start_slicing = slice_starter or (lambda: start_slice_scan(store.videos_root))

    @app.get("/api/rooms")
    async def list_rooms() -> list[Dict[str, Any]]:
        return [room.to_dict() for room in store.list_rooms()]

    @app.get("/api/slices")
    async def list_slices(room_id: str | None = None) -> list[Dict[str, Any]]:
        try:
            return [item.to_dict() for item in store.list_slices(room_id)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/slice-progress")
    async def get_slice_progress() -> Dict[str, Any]:
        progress = load_progress_state()
        queue_state = load_pending_queue_state(store.videos_root)
        if queue_state["pending_tasks"] and (
            progress["status"] == "idle" or progress.get("stale")
        ):
            progress.update(
                status="queued",
                phase="queued",
                phase_label="已排队",
                message="等待本机 PC 切片 worker 处理",
                current_slice_percent=0.0,
                stale=False,
                **queue_state,
            )
        else:
            progress.update(queue_state)
        return progress

    @app.post("/api/slice/start")
    async def start_slice() -> Dict[str, Any]:
        try:
            return start_slicing()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.patch("/api/slices/{slice_id}/feedback")
    async def update_feedback(
        slice_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            return store.write_feedback(slice_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/media/{media_id}")
    async def get_media(media_id: str, request: Request) -> Response:
        try:
            path = store.resolve_media(media_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return media_response(path, request)

    @app.get("/api/preview/{media_id}")
    async def get_preview(media_id: str, request: Request) -> Response:
        try:
            path = store.resolve_preview_media(media_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return media_response(path, request, media_type="video/mp4")

    if static_dir:
        static_path = Path(static_dir)
        if static_path.is_dir():
            index_path = static_path / "index.html"

            if index_path.is_file():

                @app.get("/tasks", include_in_schema=False)
                async def tasks_page() -> FileResponse:
                    return FileResponse(index_path)

            app.mount("/", StaticFiles(directory=static_path, html=True), name="web")

    return app


api = create_app(
    static_dir=os.environ.get(
        "BILIVE_DASHBOARD_STATIC",
        str(Path(__file__).resolve().parents[2] / "frontend"),
    )
)
