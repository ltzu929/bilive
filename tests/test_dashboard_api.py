import httpx
import pytest

from src.dashboard.app import create_app


@pytest.mark.anyio
async def test_slices_api_lists_candidates(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "3100s_8792912_20260506-18-56-51.mp4"


@pytest.mark.anyio
async def test_feedback_api_updates_sidecar(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slice_id = (await client.get("/api/slices?room_id=8792912")).json()[0]["id"]
        response = await client.patch(
            f"/api/slices/{slice_id}/feedback",
            json={"decision": "keep", "quality_reason": "值得精切"},
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "keep"


@pytest.mark.anyio
async def test_media_api_serves_mp4_source(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"mp4")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/media/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_media_api_supports_byte_ranges_for_seek(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"0123456789")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(
            f"/api/media/{item['media_id']}",
            headers={"Range": "bytes=2-5"},
        )

    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_preview_media_api_serves_mp4_source(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"mp4")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/preview/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_preview_media_api_supports_byte_ranges_for_seek(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"0123456789")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(
            f"/api/preview/{item['media_id']}",
            headers={"Range": "bytes=6-"},
        )

    assert response.status_code == 206
    assert response.content == b"6789"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 6-9/10"
    assert response.headers["content-length"] == "4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_preview_media_api_remuxes_flv_to_cached_mp4(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3130s_8792912_20260506-18-56-51.flv").write_bytes(b"flv")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        output_path = command[-1]
        output_path.write_bytes(b"mp4-preview")

    monkeypatch.setattr("src.dashboard.file_store.subprocess.run", fake_run)
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/preview/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4-preview"
    assert response.headers["content-type"].startswith("video/mp4")
    assert commands
    assert commands[0][:4] == ["ffmpeg", "-y", "-i", room / "3130s_8792912_20260506-18-56-51.flv"]


@pytest.mark.anyio
async def test_rooms_api_lists_video_rooms(tmp_path):
    videos = tmp_path / "Videos"
    (videos / "8792912").mkdir(parents=True)
    (videos / "22384516").mkdir(parents=True)

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/rooms")

    assert response.status_code == 200
    assert response.json() == [
        {"room_id": "22384516"},
        {"room_id": "8792912"},
    ]


@pytest.mark.anyio
async def test_app_uses_videos_root_from_env(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")
    monkeypatch.setenv("BILIVE_VIDEOS_DIR", str(videos))

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "3100s_8792912_20260506-18-56-51.mp4"


@pytest.mark.anyio
async def test_tasks_route_serves_static_frontend(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<main id=\"app\"></main>", encoding="utf-8")

    transport = httpx.ASGITransport(
        app=create_app(videos_root=tmp_path / "Videos", static_dir=frontend)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/tasks")

    assert response.status_code == 200
    assert "id=\"app\"" in response.text
