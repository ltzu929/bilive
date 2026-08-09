from src.server.studio_proxy import is_studio_api_request, upstream_path


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
