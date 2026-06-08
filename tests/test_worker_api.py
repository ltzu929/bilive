import httpx
import pytest

from src.server.worker_api import _auto_upload_enabled, create_app


@pytest.mark.anyio
async def test_worker_api_starts_one_shot_worker():
    calls = []

    def fake_starter():
        calls.append("start")
        return {"status": "started", "pid": 1234}

    transport = httpx.ASGITransport(app=create_app(worker_starter=fake_starter))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/worker/run-once",
            headers={"Origin": "http://192.168.31.157:2234"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "pid": 1234}
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-private-network"] == "true"
    assert calls == ["start"]


@pytest.mark.anyio
async def test_worker_api_reports_start_errors():
    def fake_starter():
        raise RuntimeError("worker failed")

    transport = httpx.ASGITransport(app=create_app(worker_starter=fake_starter))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/worker/run-once")

    assert response.status_code == 500
    assert response.json()["detail"] == "worker failed"


@pytest.mark.anyio
async def test_worker_api_reports_status():
    transport = httpx.ASGITransport(
        app=create_app(worker_status_reader=lambda: {"status": "idle"})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/worker/status")

    assert response.status_code == 200
    assert response.json() == {"status": "idle"}


@pytest.mark.anyio
async def test_worker_api_lifespan_starts_and_stops_upload_worker():
    calls = []

    def start_upload():
        calls.append("start")
        return {"status": "started", "pid": 4321}

    def stop_upload():
        calls.append("stop")
        return {"status": "stopped", "pid": 4321}

    app = create_app(
        upload_starter=start_upload,
        upload_stopper=stop_upload,
        auto_upload=True,
    )

    async with app.router.lifespan_context(app):
        assert calls == ["start"]

    assert calls == ["start", "stop"]


@pytest.mark.anyio
async def test_worker_api_lifespan_can_disable_auto_upload():
    calls = []
    app = create_app(
        upload_starter=lambda: calls.append("start"),
        upload_stopper=lambda: calls.append("stop"),
        auto_upload=False,
    )

    async with app.router.lifespan_context(app):
        assert calls == []

    assert calls == []


@pytest.mark.anyio
async def test_worker_api_reports_and_starts_upload_worker():
    starts = []
    app = create_app(
        upload_starter=lambda: starts.append("start")
        or {"status": "started", "pid": 4321},
        upload_status_reader=lambda: {
            "status": "paused_auth",
            "process_status": "running",
        },
        auto_upload=False,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status_response = await client.get("/api/upload/status")
        start_response = await client.post("/api/upload/start")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "paused_auth"
    assert start_response.status_code == 200
    assert start_response.json() == {"status": "started", "pid": 4321}
    assert starts == ["start"]


@pytest.mark.anyio
async def test_worker_api_reports_upload_start_errors():
    def fail_start():
        raise RuntimeError("upload failed")

    app = create_app(upload_starter=fail_start, auto_upload=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/upload/start")

    assert response.status_code == 500
    assert response.json()["detail"] == "upload failed"


def test_auto_upload_environment_override(monkeypatch):
    monkeypatch.setenv("BILIVE_AUTO_UPLOAD", "0")
    assert _auto_upload_enabled() is False

    monkeypatch.setenv("BILIVE_AUTO_UPLOAD", "true")
    assert _auto_upload_enabled() is True
