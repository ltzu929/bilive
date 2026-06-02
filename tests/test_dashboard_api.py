import json
import time
from types import SimpleNamespace

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
async def test_feedback_api_persists_reviewed_at_and_review_source(tmp_path):
    """PATCH feedback adds reviewed_at timestamp and review_source='dashboard'."""
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
    body = response.json()
    assert body["decision"] == "keep"
    assert "reviewed_at" in body
    assert body["reviewed_at"] is not None
    assert body["review_source"] == "dashboard"


@pytest.mark.anyio
async def test_feedback_api_preserves_reviewed_at_on_update(tmp_path):
    """Subsequent PATCH preserves the original reviewed_at."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slice_id = (await client.get("/api/slices?room_id=8792912")).json()[0]["id"]
        first = await client.patch(
            f"/api/slices/{slice_id}/feedback",
            json={"decision": "review"},
        )
        first_reviewed_at = first.json()["reviewed_at"]

        second = await client.patch(
            f"/api/slices/{slice_id}/feedback",
            json={"decision": "keep"},
        )

    assert second.status_code == 200
    assert second.json()["reviewed_at"] == first_reviewed_at


def test_normalize_feedback_preserves_reviewed_at_and_review_source(tmp_path):
    """_normalize_feedback preserves reviewed_at and review_source from data."""
    from src.dashboard.file_store import DashboardFileStore

    store = DashboardFileStore(videos_root=tmp_path / "Videos")
    room = tmp_path / "Videos" / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")

    items = store.list_slices(room_id="8792912")
    item = items[0]
    result = store._normalize_feedback(item, {
        "decision": "keep",
        "reviewed_at": "2026-06-01T12:00:00Z",
        "review_source": "cli",
    })
    assert result["reviewed_at"] == "2026-06-01T12:00:00Z"
    assert result["review_source"] == "cli"


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
        {"room_id": "22384516", "name": "22384516"},
        {"room_id": "8792912", "name": "8792912"},
    ]


@pytest.mark.anyio
async def test_rooms_api_uses_anchor_name_from_jsonl(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260527-12-55-31.jsonl").write_text(
        json.dumps({
            "cmd": "DANMU_MSG",
            "info": [[], "", "", [30, "小米星", "呜米", 22384516]],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/rooms")

    assert response.status_code == 200
    assert response.json() == [{"room_id": "22384516", "name": "呜米"}]


@pytest.mark.anyio
async def test_tasks_api_uses_anchor_name_from_room_metadata(tmp_path):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    (room / "22384516_20260527-12-55-31.jsonl").write_text(
        json.dumps({
            "cmd": "DANMU_MSG",
            "info": [[], "", "", [30, "小米星", "呜米", 22384516]],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json()[0]["room_name"] == "呜米"


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

    def fake_start_slice(_opts=None):
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
async def test_start_slice_api_accepts_legacy_zero_arg_starter(tmp_path):
    calls = []

    def fake_start_slice():
        calls.append("start")
        return {"status": "started"}

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
    assert calls == ["start"]


@pytest.mark.anyio
async def test_start_slice_api_reports_start_errors(tmp_path):
    def fake_start_slice(_opts=None):
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


# ── Milestone 4: Quality Explanation Panel ──


@pytest.mark.anyio
async def test_slice_item_includes_quality_fields_from_feedback_sidecar(tmp_path):
    """SliceItem populates quality_score, burst_ratio, burst_rank from _feedback.json."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    mp4 = room / "3100s_8792912_20260506-18-56-51.mp4"
    mp4.write_bytes(b"clip")
    feedback = room / "3100s_8792912_20260506-18-56-51_feedback.json"
    feedback.write_text(
        json.dumps({
            "decision": "keep",
            "quality_reason": "high burst ratio",
            "quality_score": 0.85,
            "burst_ratio": 4.2,
            "burst_rank": 1,
        }),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["quality_score"] == 0.85
    assert item["burst_ratio"] == 4.2
    assert item["burst_rank"] == 1


@pytest.mark.anyio
async def test_slice_item_quality_fields_default_none_without_sidecar(tmp_path):
    """Without feedback sidecar, quality fields are None."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    (room / "3100s_8792912_20260506-18-56-51.mp4").write_bytes(b"clip")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["quality_score"] is None
    assert item["burst_ratio"] is None
    assert item["burst_rank"] is None


@pytest.mark.anyio
async def test_slice_item_reads_quality_from_analysis_sidecar(tmp_path):
    """SliceItem reads quality fields from _analysis.json when feedback lacks them."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    mp4 = room / "3100s_8792912_20260506-18-56-51.mp4"
    mp4.write_bytes(b"clip")
    analysis = room / "3100s_8792912_20260506-18-56-51_analysis.json"
    analysis.write_text(
        json.dumps({
            "quality_score": 0.72,
            "burst_ratio": 3.1,
            "burst_rank": 2,
        }),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["quality_score"] == 0.72
    assert item["burst_ratio"] == 3.1
    assert item["burst_rank"] == 2


@pytest.mark.anyio
async def test_feedback_sidecar_overrides_analysis_for_quality_fields(tmp_path):
    """Feedback sidecar takes priority over analysis sidecar for quality fields."""
    videos = tmp_path / "Videos"
    room = videos / "8792912"
    room.mkdir(parents=True)
    mp4 = room / "3100s_8792912_20260506-18-56-51.mp4"
    mp4.write_bytes(b"clip")
    analysis = room / "3100s_8792912_20260506-18-56-51_analysis.json"
    analysis.write_text(
        json.dumps({
            "quality_score": 0.5,
            "burst_ratio": 2.0,
            "burst_rank": 3,
        }),
        encoding="utf-8",
    )
    feedback = room / "3100s_8792912_20260506-18-56-51_feedback.json"
    feedback.write_text(
        json.dumps({
            "decision": "keep",
            "quality_score": 0.9,
            "burst_ratio": 5.0,
            "burst_rank": 1,
        }),
        encoding="utf-8",
    )

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["quality_score"] == 0.9
    assert item["burst_ratio"] == 5.0
    assert item["burst_rank"] == 1


# ── Milestone 5: Burst Parameter Tuning ──


@pytest.mark.anyio
async def test_start_slice_rejects_invalid_burst_ratio(tmp_path):
    """POST /api/slice/start rejects burst_ratio outside 1.5-8.0."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_ratio": 1.0}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_invalid_burst_top_n(tmp_path):
    """POST /api/slice/start rejects burst_top_n outside 1-5."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_top_n": 6}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_non_object_slice_options(tmp_path):
    """slice_options must be a JSON object."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/slice/start", json={"slice_options": "bad"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_non_numeric_burst_ratio(tmp_path):
    """burst_ratio must be numeric."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_ratio": "bad"}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_accepts_valid_slice_options(tmp_path):
    """POST /api/slice/start with valid slice_options proceeds."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/slice/start", json={
            "slice_options": {
                "burst_ratio": 3.0,
                "burst_top_n": 3,
                "burst_context": 60,
                "burst_window": 10,
                "burst_merge_gap": 5,
            }
        })
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_refine_preview_uses_dry_run_without_upload(tmp_path, monkeypatch):
    calls = []

    def fake_process(root, enqueue_upload=True, dry_run=False):
        calls.append((root, enqueue_upload, dry_run))
        return [
            SimpleNamespace(
                decision="keep",
                status="would_refine",
                feedback_path="keep_feedback.json",
                message="would generate keep_refined.mp4",
            ),
            SimpleNamespace(
                decision="drop",
                status="skipped_decision",
                feedback_path="drop_feedback.json",
                message="decision=drop is not queued",
            ),
        ]

    videos = tmp_path / "Videos"
    monkeypatch.setattr("src.dashboard.app.process_feedback_directory", fake_process)
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/refine/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["keep_count"] == 1
    assert body["drop_count"] == 1
    assert body["would_generate"][0]["status"] == "would_refine"
    assert calls == [(videos, False, True)]


@pytest.mark.anyio
async def test_refine_run_does_not_enqueue_upload_by_default(tmp_path, monkeypatch):
    calls = []

    def fake_process(root, enqueue_upload=True, dry_run=False):
        calls.append((root, enqueue_upload, dry_run))
        return [
            SimpleNamespace(decision="keep", status="refined"),
            SimpleNamespace(decision="keep", status="refine_failed"),
        ]

    videos = tmp_path / "Videos"
    monkeypatch.setattr("src.dashboard.app.process_feedback_directory", fake_process)
    transport = httpx.ASGITransport(app=create_app(videos_root=videos))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/refine/run")

    assert response.status_code == 200
    assert response.json() == {
        "keep_count": 2,
        "refined": 1,
        "failed": 1,
        "upload_queued": False,
    }
    assert calls == [(videos, False, False)]
