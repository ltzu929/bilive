"""Expose the Windows Studio API through the recorder origin.

The recorder UI is served by blrec on port 2233, while the slice, upload and
settings APIs remain in the Windows dashboard on port 2234.  This gateway is
deliberately narrow: only requests under ``/studio-api`` are forwarded.  The
recorder's own ``/api`` and ``/api/v1`` routes therefore remain untouched and
there is no referer or iframe compatibility path to maintain.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from typing import Iterable
from urllib.parse import urlsplit

import aiohttp
from starlette.types import ASGIApp, Receive, Scope, Send


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _header_map(scope: Scope) -> dict[str, str]:
    return {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in scope.get("headers", [])
    }


def _path_with_query(scope: Scope) -> str:
    path = scope.get("path", "/") or "/"
    query = scope.get("query_string", b"")
    if query:
        return f"{path}?{query.decode('latin-1')}"
    return path


def is_studio_api_request(scope: Scope, prefix: str = "/studio-api") -> bool:
    """Return whether an HTTP request belongs to the Studio API gateway."""
    if scope.get("type") != "http":
        return False
    normalized = prefix.rstrip("/") or "/studio-api"
    path = scope.get("path", "")
    return path == normalized or path.startswith(f"{normalized}/")


def upstream_path(scope: Scope, *, prefix: str = "/studio-api") -> str:
    """Map ``/studio-api/foo`` to dashboard ``/api/foo``."""
    normalized = prefix.rstrip("/") or "/studio-api"
    path = scope.get("path", "/") or "/"
    if path == normalized:
        suffix = ""
    elif path.startswith(f"{normalized}/"):
        suffix = path[len(normalized) :]
    else:
        raise ValueError(f"path is outside Studio API prefix: {path}")
    path = f"/api{suffix or ''}"
    query = scope.get("query_string", b"")
    if query:
        return f"{path}?{query.decode('latin-1')}"
    return path


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def _send_error(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _wait_for_disconnect(receive: Receive) -> None:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return


async def _stream_response(
    response: aiohttp.ClientResponse,
    receive: Receive,
    send: Send,
) -> None:
    disconnect_task = asyncio.create_task(_wait_for_disconnect(receive))
    try:
        while True:
            read_task = asyncio.create_task(response.content.read(64 * 1024))
            done, _ = await asyncio.wait(
                {read_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done:
                read_task.cancel()
                with suppress(asyncio.CancelledError):
                    await read_task
                response.close()
                return

            chunk = read_task.result()
            if not chunk:
                break
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b""})
    finally:
        disconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_task


def _request_headers(scope: Scope, upstream_origin: str) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1")
        lower_name = name.lower()
        if lower_name in HOP_BY_HOP_HEADERS or lower_name in {
            "host",
            "content-length",
            "origin",
        }:
            continue
        headers.append((name, raw_value.decode("latin-1")))
    headers.append(("Host", urlsplit(upstream_origin).netloc))
    if _header_map(scope).get("origin"):
        headers.append(("Origin", upstream_origin))
    return headers


def _response_headers(
    response: aiohttp.ClientResponse, prefix: str
) -> Iterable[tuple[bytes, bytes]]:
    for raw_name, raw_value in response.raw_headers:
        lower_name = raw_name.decode("latin-1").lower()
        if lower_name in HOP_BY_HOP_HEADERS:
            continue
        if lower_name == "location":
            location = raw_value.decode("latin-1")
            if location.startswith("/api"):
                location = f"{prefix}{location[4:]}"
            raw_value = location.encode("latin-1")
        yield raw_name, raw_value


class StudioApiMiddleware:
    """Forward only the explicit Studio API/media namespace."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        upstream: str | None = None,
        prefix: str | None = None,
    ) -> None:
        self._app = app
        self._upstream = (
            upstream
            or os.environ.get("BILIVE_STUDIO_API_UPSTREAM")
            or "http://127.0.0.1:2234"
        ).rstrip("/")
        self._prefix = (
            prefix
            or os.environ.get("BILIVE_STUDIO_API_PREFIX")
            or "/studio-api"
        ).rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not is_studio_api_request(scope, self._prefix):
            await self._app(scope, receive, send)
            return
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        target = f"{self._upstream}{upstream_path(scope, prefix=self._prefix)}"
        body = await _read_body(receive) if method not in {"GET", "HEAD"} else b""
        response_started = False
        try:
            timeout = aiohttp.ClientTimeout(total=None)
            async with aiohttp.ClientSession(
                timeout=timeout, auto_decompress=False
            ) as session:
                async with session.request(
                    method,
                    target,
                    headers=_request_headers(scope, self._upstream),
                    data=body or None,
                    allow_redirects=False,
                ) as response:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": response.status,
                            "headers": list(_response_headers(response, self._prefix)),
                        }
                    )
                    response_started = True
                    if method == "HEAD":
                        await send({"type": "http.response.body", "body": b""})
                        return
                    await _stream_response(response, receive, send)
        except (aiohttp.ClientError, OSError) as exc:
            if response_started:
                return
            await _send_error(send, 502, f"Studio dashboard unavailable: {exc}")


__all__ = ["StudioApiMiddleware", "is_studio_api_request", "upstream_path"]
