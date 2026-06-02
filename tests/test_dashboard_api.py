import json
import time

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
            json={"decision": "keep", "quality_reason": "worth keeping"},
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
    assert commands[0][:4] == [
        "ffmpeg",
        "-y",
        "-i",
        room / "3130s_8792912_20260506-18-56-51.flv",
    ]


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
async def test_slice_progress_api_returns_idle_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


@pytest.mark.anyio
async def test_start_slice_api_invokes_slice_starter(tmp_path):
    calls = []

    def fake_start_slice():
        calls.append("start")
        return {
            "status": "started",
            "pid": 1234,
            "log_path": str(tmp_path / "logs" / "runtime" / "slice.log"),
        }

    transport = httpx.ASGITransport(
        app=create_app(
            videos_root=tmp_path / "Videos",
            slice_starter=fake_start_slice,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["pid"] == 1234
    assert calls == ["start"]


@pytest.mark.anyio
async def test_start_slice_api_reports_start_errors(tmp_path):
    def fake_start_slice():
        raise RuntimeError("slice scanner failed")

    transport = httpx.ASGITransport(
        app=create_app(
            videos_root=tmp_path / "Videos",
            slice_starter=fake_start_slice,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 500
    assert response.json()["detail"] == "slice scanner failed"


@pytest.mark.anyio
async def test_slice_progress_api_reads_runtime_file(tmp_path, monkeypatch):
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "slice",
                "phase_label": "切片中",
                "current_slice_percent": 42.5,
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["phase_label"] == "切片中"
    assert response.json()["current_slice_percent"] == 42.5


@pytest.mark.anyio
async def test_slice_progress_api_marks_stale(tmp_path, monkeypatch):
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "slice",
                "updated_at": time.time() - 600,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["stale"] is True


@pytest.mark.anyio
async def test_slice_progress_api_reports_pending_queue(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "8792912_20260524-13-06-05.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["phase_label"] == "已排队"
    assert response.json()["message"] == "等待本机 PC 切片 worker 处理"
    assert response.json()["pending_tasks"] == 1


@pytest.mark.anyio
async def test_slice_diagnostics_api_returns_structured_items(tmp_path, monkeypatch):
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "complete",
                "phase": "complete",
                "source_name": "22966160_20260525-12-00-19.mp4",
                "message": "未生成切片，源文件已保留",
                "updated_at": time.time(),
                "diagnostics": [
                    {
                        "id": "burst",
                        "title": "爆点检测",
                        "status": "warning",
                        "message": "未检测到超过阈值的弹幕突增",
                        "details": [
                            {"label": "弹幕数", "value": "5328"},
                            {"label": "阈值", "value": "3.0x"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["source_name"] == "22966160_20260525-12-00-19.mp4"
    assert payload["items"][0]["title"] == "爆点检测"
    assert payload["items"][0]["details"][1] == {"label": "阈值", "value": "3.0x"}


@pytest.mark.anyio
async def test_slice_diagnostics_api_reports_pending_queue(tmp_path, monkeypatch):
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "8792912_20260524-13-06-05.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slice-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["items"][0]["id"] == "queue"
    assert payload["items"][0]["message"] == "等待本机 PC 切片 worker 处理"


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
