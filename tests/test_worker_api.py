import httpx
import pytest

from src.server.worker_api import create_app


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
