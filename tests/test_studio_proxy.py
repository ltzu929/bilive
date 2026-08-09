from src.server.studio_proxy import is_studio_proxy_request, upstream_path


def _scope(path, *, query=b"", headers=()):
    return {
        "type": "http",
        "path": path,
        "query_string": query,
        "headers": list(headers),
    }


def test_studio_proxy_strips_public_prefix_and_keeps_query():
    scope = _scope("/studio-proxy/tasks", query=b"embed=blrec")

    assert is_studio_proxy_request(scope)
    assert upstream_path(scope) == "/tasks?embed=blrec"


def test_studio_proxy_routes_absolute_dashboard_assets_from_embedded_referer():
    scope = _scope(
        "/api/source-recordings",
        headers=[
            (
                b"referer",
                b"https://recorder.example/studio-proxy/tasks?embed=blrec",
            )
        ],
    )

    assert is_studio_proxy_request(scope)
    assert upstream_path(scope) == "/api/source-recordings"


def test_studio_proxy_does_not_capture_native_recorder_requests():
    scope = _scope("/api/tasks")

    assert not is_studio_proxy_request(scope)
