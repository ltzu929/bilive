import asyncio

import pytest

from src.server.studio_proxy import (
    _stream_response,
    is_studio_api_request,
    upstream_path,
)


def _scope(path, *, query=b"", headers=()):
    return {
        "type": "http",
        "path": path,
        "query_string": query,
        "headers": list(headers),
    }


def test_studio_api_strips_public_prefix_and_adds_dashboard_api_prefix():
    scope = _scope("/studio-api/source-recordings", query=b"room_id=22384516")

    assert is_studio_api_request(scope)
    assert upstream_path(scope) == "/api/source-recordings?room_id=22384516"


def test_studio_api_preserves_media_paths():
    scope = _scope("/studio-api/media/clip.mp4")

    assert upstream_path(scope) == "/api/media/clip.mp4"


def test_studio_api_does_not_capture_recorder_routes_or_referers():
    assert not is_studio_api_request(_scope("/api/tasks"))
    assert not is_studio_api_request(
        _scope(
            "/api/source-recordings",
            headers=[(b"referer", b"https://recorder.example/studio/slices")],
        )
    )


def test_studio_api_requires_explicit_prefix():
    scope = _scope("/studio-proxy/tasks")

    assert not is_studio_api_request(scope)


class _FakeContent:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""


class _BlockingContent:
    def __init__(self):
        self.cancelled = False

    async def read(self, _size):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_studio_proxy_streams_response_to_completion():
    response = _FakeResponse(_FakeContent([b"one", b"two"]))
    sent = []
    never_disconnects = asyncio.Event()

    async def receive():
        await never_disconnects.wait()

    async def send(message):
        sent.append(message)

    await _stream_response(response, receive, send)

    assert [message.get("body") for message in sent] == [b"one", b"two", b""]
    assert sent[0]["more_body"] is True
    assert sent[1]["more_body"] is True
    assert "more_body" not in sent[2]


@pytest.mark.anyio
async def test_studio_proxy_closes_upstream_when_client_disconnects():
    content = _BlockingContent()
    response = _FakeResponse(content)
    sent = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await _stream_response(response, receive, send)

    assert response.closed is True
    assert content.cancelled is True
    assert sent == []
