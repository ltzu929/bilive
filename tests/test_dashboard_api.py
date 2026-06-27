import json
import base64
from pathlib import Path
import time
from types import SimpleNamespace

import pytest


@pytest.mark.anyio
async def test_slices_api_lists_candidates(videos_root, write_slice, dashboard_client):
    write_slice()

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "3100s_8792912_20260506-18-56-51.mp4"


@pytest.mark.anyio
async def test_feedback_api_updates_sidecar(videos_root, write_slice, dashboard_client):
    write_slice()

    async with dashboard_client(videos_root) as client:
        slice_id = (await client.get("/api/slices?room_id=8792912")).json()[0]["id"]
        response = await client.patch(
            f"/api/slices/{slice_id}/feedback",
            json={"decision": "keep", "quality_reason": "worth keeping"},
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "keep"


@pytest.mark.anyio
async def test_feedback_api_persists_reviewed_at_and_review_source(
    videos_root,
    write_slice,
    dashboard_client,
):
    """PATCH feedback adds reviewed_at timestamp and review_source='dashboard'."""
    write_slice()

    async with dashboard_client(videos_root) as client:
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
async def test_feedback_api_preserves_reviewed_at_on_update(
    videos_root,
    write_slice,
    dashboard_client,
):
    """Subsequent PATCH preserves the original reviewed_at."""
    write_slice()

    async with dashboard_client(videos_root) as client:
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


def test_normalize_feedback_preserves_reviewed_at_and_review_source(videos_root, write_slice):
    """_normalize_feedback preserves reviewed_at and review_source from data."""
    from src.dashboard.file_store import DashboardFileStore

    store = DashboardFileStore(videos_root=videos_root)
    write_slice()

    items = store.list_slices(room_id="8792912")
    item = items[0]
    result = store._normalize_feedback(item, {
        "decision": "keep",
        "reviewed_at": "2026-06-01T12:00:00Z",
        "review_source": "cli",
    })
    assert result["reviewed_at"] == "2026-06-01T12:00:00Z"
    assert result["review_source"] == "cli"


def test_media_range_response_streams_instead_of_buffering(tmp_path):
    from fastapi import Request
    from fastapi.responses import StreamingResponse

    from src.dashboard.app import media_response

    media = tmp_path / "large.mp4"
    media.write_bytes(b"0123456789")
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/media/test",
        "headers": [(b"range", b"bytes=0-")],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1234),
        "scheme": "http",
        "http_version": "1.1",
    })

    response = media_response(media, request)

    assert isinstance(response, StreamingResponse)
    assert response.status_code == 206
    assert response.headers["content-length"] == "10"


@pytest.mark.anyio
async def test_media_api_serves_mp4_source(videos_root, write_slice, dashboard_client):
    write_slice(content=b"mp4")

    async with dashboard_client(videos_root) as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/media/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_media_api_supports_byte_ranges_for_seek(
    videos_root,
    write_slice,
    dashboard_client,
):
    write_slice(content=b"0123456789")

    async with dashboard_client(videos_root) as client:
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
async def test_preview_media_api_serves_mp4_source(videos_root, write_slice, dashboard_client):
    write_slice(content=b"mp4")

    async with dashboard_client(videos_root) as client:
        item = (await client.get("/api/slices?room_id=8792912")).json()[0]
        response = await client.get(f"/api/preview/{item['media_id']}")

    assert response.status_code == 200
    assert response.content == b"mp4"
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.anyio
async def test_preview_media_api_supports_byte_ranges_for_seek(
    videos_root,
    write_slice,
    dashboard_client,
):
    write_slice(content=b"0123456789")

    async with dashboard_client(videos_root) as client:
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
async def test_preview_media_api_remuxes_flv_to_cached_mp4(
    videos_root,
    make_room,
    dashboard_client,
    monkeypatch,
):
    room = make_room("8792912")
    (room / "3130s_8792912_20260506-18-56-51.flv").write_bytes(b"flv")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        output_path = command[-1]
        output_path.write_bytes(b"mp4-preview")

    monkeypatch.setattr("src.dashboard.file_store.subprocess.run", fake_run)

    async with dashboard_client(videos_root) as client:
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
async def test_rooms_api_lists_video_rooms(make_room, videos_root, dashboard_client):
    make_room("8792912")
    make_room("22384516")

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/rooms")

    assert response.status_code == 200
    assert response.json() == [
        {"room_id": "22384516", "name": "22384516"},
        {"room_id": "8792912", "name": "8792912"},
    ]


@pytest.mark.anyio
async def test_rooms_api_uses_anchor_name_from_jsonl(make_room, videos_root, dashboard_client):
    room = make_room("22384516")
    (room / "22384516_20260527-12-55-31.jsonl").write_text(
        json.dumps({
            "cmd": "DANMU_MSG",
            "info": [[], "", "", [30, "小米星", "呜米", 22384516]],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/rooms")

    assert response.status_code == 200
    assert response.json() == [{"room_id": "22384516", "name": "呜米"}]


@pytest.mark.anyio
async def test_tasks_api_uses_anchor_name_from_room_metadata(
    make_room,
    videos_root,
    dashboard_client,
):
    room = make_room("22384516")
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

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json()[0]["room_name"] == "呜米"


def _write_source_workbench_fixture(videos):
    from src.burn.task_history import write_task_history

    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<i>\n"
        "  <d p=\"1,1,25,16777215,0,0,0,0\">a</d>\n"
        "  <d p=\"11,1,25,16777215,0,0,0,0\">b</d>\n"
        "</i>\n",
        encoding="utf-8",
    )
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    candidate = room / "10s_22384516_20260602-12-56-49.mp4"
    candidate.write_bytes(b"clip")
    write_task_history(
        source,
        status="done",
        videos_root=videos,
        segments=[
            {
                "segment_id": "seg1",
                "candidate_path": str(candidate),
                "candidate_rel_path": "22384516/10s_22384516_20260602-12-56-49.mp4",
                "start_seconds": 10.0,
                "end_seconds": 70.0,
                "judge_status": "keep",
                "upload_status": "queued",
            }
        ],
    )
    return source


@pytest.mark.anyio
async def test_source_recordings_api_lists_summary_counts(videos_root, dashboard_client):
    _write_source_workbench_fixture(videos_root)

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/source-recordings")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["summary_counts"]["keep"] == 1
    assert body[0]["source_name"] == "22384516_20260602-12-56-49.mp4"


def test_upload_path_parts_normalizes_windows_paths():
    from src.dashboard.app import upload_path_parts

    name, room = upload_path_parts(
        r"D:\alldata\pi\bilive\Videos\22384516\clip.mp4"
    )

    assert name == "clip.mp4"
    assert room == "22384516"


def test_dashboard_settings_exposes_mimo_parallelism():
    from src.dashboard.app import read_dashboard_settings

    settings = read_dashboard_settings()

    assert settings["mimo"]["parallelism"] == 3

def test_upload_dashboard_missing_database_is_read_only(tmp_path, monkeypatch):
    from src.db import conn
    from src.dashboard.app import read_upload_dashboard

    missing_db = tmp_path / "missing-upload.db"
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(missing_db))

    payload = read_upload_dashboard()

    assert payload["database"].startswith("unavailable")
    assert payload["queue_counts"]["total"] == 0
    assert payload["items"] == []
    assert not missing_db.exists()

@pytest.mark.anyio
async def test_dashboard_secondary_pages_and_runtime_apis(
    videos_root,
    dashboard_client,
    monkeypatch,
):
    from src.dashboard import app as dashboard_app

    monkeypatch.setattr(
        dashboard_app,
        "read_upload_dashboard",
        lambda: {
            "queue_counts": {"queued": 1, "published": 2, "failed": 0, "total": 3},
            "items": [{"id": 1, "name": "clip.mp4", "status": "queued"}],
            "worker": {"process_status": "running"},
        },
    )
    monkeypatch.setattr(
        dashboard_app,
        "read_dashboard_settings",
        lambda: {
            "slice": {"burst_ratio": 3.0, "burst_context": 60},
            "mimo": {"model": "mimo-v2.5", "configured": True},
            "whisper": {"model": "large-v3", "device": "cpu"},
            "upload": {"auto_start": True, "max_attempts": 3},
        },
    )

    async with dashboard_client(videos_root, static_dir=Path("frontend")) as client:
        uploads_page = await client.get("/uploads")
        settings_page = await client.get("/settings")
        uploads = await client.get("/api/upload-dashboard")
        settings = await client.get("/api/dashboard-settings")

    assert uploads_page.status_code == 200
    assert settings_page.status_code == 200
    assert uploads.json()["items"][0]["name"] == "clip.mp4"
    assert settings.json()["mimo"]["model"] == "mimo-v2.5"


@pytest.mark.anyio
async def test_source_recording_detail_api_returns_density_and_segments(
    videos_root,
    dashboard_client,
):
    _write_source_workbench_fixture(videos_root)

    async with dashboard_client(videos_root) as client:
        item = (await client.get("/api/source-recordings")).json()[0]
        response = await client.get(f"/api/source-recordings/{item['task_id']}")
        media = await client.get(f"/api/media/{response.json()['source_media_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["density_points"][0]["count"] == 1
    assert body["segments"][0]["judge_status"] == "keep"
    assert media.status_code == 200
    assert media.content == b"video"


@pytest.mark.anyio
async def test_segment_action_apis_update_segment_sidecar(
    videos_root,
    dashboard_client,
    monkeypatch,
):
    from src.dashboard import source_workbench

    _write_source_workbench_fixture(videos_root)
    queued = []
    heavy_calls = []

    monkeypatch.setattr(source_workbench, "insert_upload_queue", lambda path: queued.append(path) or True)
    monkeypatch.setattr(source_workbench, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        source_workbench,
        "retry_segment_judge",
        lambda *args, **kwargs: heavy_calls.append("retry"),
    )
    monkeypatch.setattr(
        source_workbench,
        "render_segment",
        lambda *args, **kwargs: heavy_calls.append("render"),
    )

    async with dashboard_client(videos_root) as client:
        keep = await client.post(
            "/api/segments/seg1/manual-keep",
            json={"title": "Manual", "description": "Desc", "tags": ["live"]},
        )
        ranged = await client.post(
            "/api/segments/seg1/range",
            json={"start_seconds": 5, "end_seconds": 25},
        )
        dropped = await client.post("/api/segments/seg1/drop", json={"reason": "bad"})
        retried = await client.post("/api/segments/seg1/retry-judge")
        rendered = await client.post("/api/segments/seg1/render")
        retry_job = await client.get(retried.json()["status_url"])
        render_job = await client.get(rendered.json()["status_url"])

    assert keep.status_code == 200
    assert keep.json()["judge_status"] == "manual_keep"
    assert queued
    assert ranged.json()["start_seconds"] == 5.0
    assert dropped.json()["judge_status"] == "drop"
    assert retried.status_code == 200
    assert retried.json()["status"] == "accepted"
    assert retried.json()["job"]["action"] == "retry_judge"
    assert rendered.status_code == 200
    assert rendered.json()["status"] == "accepted"
    assert rendered.json()["job"]["action"] == "render_segment"
    assert heavy_calls == []

    assert retry_job.json()["status"] == "pending"
    assert render_job.json()["status"] == "pending"


@pytest.mark.anyio
async def test_app_uses_videos_root_from_env(videos_root, write_slice, dashboard_client, monkeypatch):
    write_slice()
    monkeypatch.setenv("BILIVE_VIDEOS_DIR", str(videos_root))

    async with dashboard_client(None) as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "3100s_8792912_20260506-18-56-51.mp4"


@pytest.mark.anyio
async def test_slice_progress_api_returns_idle_when_missing(
    tmp_path,
    dashboard_client,
    monkeypatch,
):
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)
    async with dashboard_client(tmp_path / "Videos") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


@pytest.mark.anyio
async def test_start_slice_api_invokes_slice_starter(tmp_path, dashboard_client):
    calls = []

    def fake_start_slice(_opts=None):
        calls.append("start")
        return {
            "status": "started",
            "pid": 1234,
            "log_path": str(tmp_path / "logs" / "runtime" / "slice.log"),
        }

    async with dashboard_client(
        tmp_path / "Videos",
        slice_starter=fake_start_slice,
    ) as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["pid"] == 1234
    assert calls == ["start"]


@pytest.mark.anyio
async def test_start_slice_api_accepts_legacy_zero_arg_starter(tmp_path, dashboard_client):
    calls = []

    def fake_start_slice():
        calls.append("start")
        return {"status": "started"}

    async with dashboard_client(
        tmp_path / "Videos",
        slice_starter=fake_start_slice,
    ) as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert calls == ["start"]


@pytest.mark.anyio
async def test_start_slice_api_reports_start_errors(tmp_path, dashboard_client):
    def fake_start_slice(_opts=None):
        raise RuntimeError("slice scanner failed")

    async with dashboard_client(
        tmp_path / "Videos",
        slice_starter=fake_start_slice,
    ) as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 500
    assert response.json()["detail"] == "slice scanner failed"


@pytest.mark.anyio
async def test_start_slice_api_triggers_remote_worker_when_tasks_are_pending(
    tmp_path,
    dashboard_client,
):
    trigger_calls = []

    def fake_start_slice(_opts=None):
        return {"status": "queued", "queued": 1, "pending_tasks": 1}

    def fake_trigger(pending_tasks):
        trigger_calls.append(pending_tasks)
        return {"status": "accepted", "pid": 1234}

    async with dashboard_client(
        tmp_path / "Videos",
        slice_starter=fake_start_slice,
        remote_worker_trigger=fake_trigger,
    ) as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 200
    assert response.json()["worker_trigger"] == {"status": "accepted", "pid": 1234}
    assert trigger_calls == [1]


@pytest.mark.anyio
async def test_requeue_api_uses_same_remote_worker_trigger(tmp_path, dashboard_client):
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i/>", encoding="utf-8")
    task_id = __import__("base64").urlsafe_b64encode(
        source.relative_to(videos).as_posix().encode()
    ).decode().rstrip("=")
    calls = []

    async with dashboard_client(
        videos,
        remote_worker_trigger=lambda pending: calls.append(pending)
        or {"status": "accepted", "pid": 22},
    ) as client:
        response = await client.post(f"/api/tasks/{task_id}/requeue")

    assert response.json()["worker_trigger"] == {"status": "accepted", "pid": 22}
    assert calls == [1]


@pytest.mark.anyio
async def test_start_slice_api_does_not_trigger_remote_worker_without_pending_tasks(
    tmp_path,
    dashboard_client,
):
    trigger_calls = []

    def fake_start_slice(_opts=None):
        return {"status": "empty", "queued": 0, "pending_tasks": 0}

    async with dashboard_client(
        tmp_path / "Videos",
        slice_starter=fake_start_slice,
        remote_worker_trigger=lambda pending_tasks: trigger_calls.append(pending_tasks),
    ) as client:
        response = await client.post("/api/slice/start")

    assert response.status_code == 200
    assert "worker_trigger" not in response.json()
    assert trigger_calls == []


@pytest.mark.anyio
async def test_worker_trigger_status_api_reports_remote_mode(tmp_path, dashboard_client):
    async with dashboard_client(
        tmp_path / "Videos",
        remote_worker_status_reader=lambda: {
            "mode": "remote",
            "enabled": True,
            "message": "Pi remote Windows task trigger is enabled",
        },
    ) as client:
        response = await client.get("/api/worker-trigger/status")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "remote",
        "enabled": True,
        "message": "Pi remote Windows task trigger is enabled",
    }


@pytest.mark.anyio
async def test_worker_wake_api_calls_remote_waker(tmp_path, dashboard_client):
    calls = []

    async with dashboard_client(
        tmp_path / "Videos",
        remote_worker_waker=lambda: calls.append("wake")
        or {
            "status": "idle",
            "mode": "remote",
            "enabled": True,
        },
    ) as client:
        response = await client.post("/api/worker-trigger/wake")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert calls == ["wake"]


@pytest.mark.anyio
async def test_worker_trigger_stop_uses_remote_worker_stopper(tmp_path, dashboard_client):
    calls = []

    async with dashboard_client(
        tmp_path / "Videos",
        remote_worker_stopper=lambda: calls.append("stop")
        or {
            "status": "stopped",
            "recovered": 1,
            "pending_tasks": 4,
        },
    ) as client:
        response = await client.post("/api/worker-trigger/stop")

    assert response.status_code == 200
    assert response.json() == {
        "status": "stopped",
        "recovered": 1,
        "pending_tasks": 4,
    }
    assert calls == ["stop"]

@pytest.mark.anyio
async def test_slice_progress_api_reads_runtime_file(tmp_path, dashboard_client, monkeypatch):
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

    async with dashboard_client(tmp_path / "Videos") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["phase_label"] == "切片中"
    assert response.json()["current_slice_percent"] == 42.5


@pytest.mark.anyio
async def test_slice_progress_api_enriches_current_recording_display(
    make_room,
    dashboard_client,
    tmp_path,
    monkeypatch,
):
    room = make_room("22384516")
    source = room / "22384516_20260617-14-23-25.mp4"
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    (room / "events.jsonl").write_text(
        json.dumps(
            {
                "cmd": "DANMU_MSG",
                "info": [None, None, None, [None, None, "呜米", "22384516"]],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "mimo_wait",
                "phase_label": "等待 MiMo 返回",
                "room_id": "22384516",
                "source_name": source.name,
                "current_slice": 1,
                "total_slices": 2,
                "updated_at": time.time(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    async with dashboard_client(tmp_path / "Videos") as client:
        response = await client.get("/api/slice-progress")

    body = response.json()
    assert body["room_name"] == "呜米"
    assert body["recorded_at"] == "2026-06-17 14:23:25"
    assert body["display_title"] == "呜米 · 2026-06-17 14:23:25"
    assert body["source_file"] == source.name
    expected_rel_path = "22384516/22384516_20260617-14-23-25.mp4"
    expected_task_id = base64.urlsafe_b64encode(
        expected_rel_path.encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert body["source_rel_path"] == expected_rel_path
    assert body["source_task_id"] == expected_task_id
    assert body["phase_label"] == "等待 MiMo 返回"

@pytest.mark.anyio
async def test_slice_progress_api_marks_stale(tmp_path, dashboard_client, monkeypatch):
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

    async with dashboard_client(tmp_path / "Videos") as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["stale"] is True


@pytest.mark.anyio
async def test_slice_progress_api_reports_pending_queue(
    videos_root,
    make_room,
    dashboard_client,
    tmp_path,
    monkeypatch,
):
    room = make_room("8792912")
    (room / "8792912_20260524-13-06-05.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["phase_label"] == "已排队"
    assert response.json()["message"] == "等待本机 PC 切片 worker 处理"
    assert response.json()["pending_tasks"] == 1


@pytest.mark.anyio
async def test_slice_progress_api_replaces_stale_running_progress_with_pending_queue(
    videos_root,
    make_room,
    dashboard_client,
    tmp_path,
    monkeypatch,
):
    room = make_room("8792912")
    (room / "8792912_20260602-10-56-23.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "analyze",
                "source_name": "old-recording.mp4",
                "current_slice": 1,
                "total_slices": 3,
                "updated_at": time.time() - 600,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["source_name"] == ""
    assert payload["current_slice"] == 0
    assert payload["total_slices"] == 0
    assert payload["pending_tasks"] == 1


@pytest.mark.anyio
async def test_slice_diagnostics_api_returns_structured_items(
    tmp_path,
    dashboard_client,
    monkeypatch,
):
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

    async with dashboard_client(tmp_path / "Videos") as client:
        response = await client.get("/api/slice-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["source_name"] == "22966160_20260525-12-00-19.mp4"
    assert payload["items"][0]["title"] == "爆点检测"
    assert payload["items"][0]["details"][1] == {"label": "阈值", "value": "3.0x"}


@pytest.mark.anyio
async def test_slice_diagnostics_api_reports_pending_queue(
    videos_root,
    make_room,
    dashboard_client,
    tmp_path,
    monkeypatch,
):
    room = make_room("8792912")
    (room / "8792912_20260524-13-06-05.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["items"][0]["id"] == "queue"
    assert payload["items"][0]["message"] == "等待本机 PC 切片 worker 处理"


@pytest.mark.anyio
async def test_slice_diagnostics_api_replaces_stale_running_progress_with_pending_queue(
    videos_root,
    make_room,
    dashboard_client,
    tmp_path,
    monkeypatch,
):
    room = make_room("8792912")
    (room / "8792912_20260602-10-56-23.mp4.pending").write_text(
        "{}",
        encoding="utf-8",
    )
    progress_path = tmp_path / "logs" / "runtime" / "slice-progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "status": "running",
                "phase": "analyze",
                "source_name": "old-recording.mp4",
                "message": "正在分析旧任务",
                "updated_at": time.time() - 600,
                "diagnostics": [
                    {
                        "id": "old",
                        "title": "旧任务",
                        "status": "ok",
                        "message": "旧诊断",
                        "details": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.delenv("BILIVE_RUNTIME_DIR", raising=False)

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slice-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["source_name"] == ""
    assert payload["items"][0]["id"] == "queue"
    assert payload["items"][0]["message"] == "等待本机 PC 切片 worker 处理"


@pytest.mark.anyio
async def test_tasks_route_serves_static_frontend(tmp_path, dashboard_client):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<main id=\"app\"></main>", encoding="utf-8")

    async with dashboard_client(tmp_path / "Videos", static_dir=frontend) as client:
        response = await client.get("/tasks")

    assert response.status_code == 200
    assert "id=\"app\"" in response.text


@pytest.mark.anyio
async def test_dashboard_rejects_non_private_host(videos_root, dashboard_client):
    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/tasks", headers={"Host": "attacker.example"})

    assert response.status_code == 400


@pytest.mark.anyio
async def test_dashboard_allows_ipv6_loopback_host(videos_root, dashboard_client):
    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/tasks", headers={"Host": "[::1]:2234"})

    assert response.status_code == 200


@pytest.mark.anyio
async def test_dashboard_rejects_cross_origin_write(videos_root, dashboard_client):
    async with dashboard_client(videos_root) as client:
        response = await client.post(
            "/api/slice/start",
            headers={"Origin": "https://attacker.example"},
        )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_slices_api_exposes_quality_fields(
    videos_root,
    make_room,
    dashboard_client,
):
    """API layer exposes quality metadata; file-store tests cover precedence rules."""
    room = make_room("8792912")
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

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/slices?room_id=8792912")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["quality_score"] == 0.85
    assert item["burst_ratio"] == 4.2
    assert item["burst_rank"] == 1


# ── Milestone 5: Burst Parameter Tuning ──


@pytest.mark.anyio
async def test_start_slice_rejects_invalid_burst_ratio(videos_root, dashboard_client):
    """POST /api/slice/start rejects burst_ratio outside 1.5-8.0."""
    async with dashboard_client(videos_root) as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_ratio": 1.0}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_invalid_burst_top_n(videos_root, dashboard_client):
    """POST /api/slice/start rejects burst_top_n outside 1-5."""
    async with dashboard_client(videos_root) as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_top_n": 6}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_non_object_slice_options(videos_root, dashboard_client):
    """slice_options must be a JSON object."""
    async with dashboard_client(videos_root) as client:
        resp = await client.post("/api/slice/start", json={"slice_options": "bad"})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_rejects_non_numeric_burst_ratio(videos_root, dashboard_client):
    """burst_ratio must be numeric."""
    async with dashboard_client(videos_root) as client:
        resp = await client.post("/api/slice/start", json={"slice_options": {"burst_ratio": "bad"}})
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_start_slice_accepts_valid_slice_options(videos_root, dashboard_client):
    """POST /api/slice/start with valid slice_options proceeds."""
    async with dashboard_client(videos_root) as client:
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
async def test_refine_preview_uses_dry_run_without_upload(
    videos_root,
    dashboard_client,
    monkeypatch,
):
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

    monkeypatch.setattr("src.dashboard.app.process_feedback_directory", fake_process)

    async with dashboard_client(videos_root) as client:
        response = await client.post("/api/refine/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["keep_count"] == 1
    assert body["drop_count"] == 1
    assert body["would_generate"][0]["status"] == "would_refine"
    assert calls == [(videos_root, False, True)]


@pytest.mark.anyio
async def test_refine_run_does_not_enqueue_upload_by_default(
    videos_root,
    dashboard_client,
    monkeypatch,
):
    calls = []

    def fake_process(root, enqueue_upload=True, dry_run=False):
        calls.append((root, enqueue_upload, dry_run))
        return [
            SimpleNamespace(decision="keep", status="refined"),
            SimpleNamespace(decision="keep", status="refine_failed"),
        ]

    monkeypatch.setattr("src.dashboard.app.process_feedback_directory", fake_process)

    async with dashboard_client(videos_root) as client:
        response = await client.post("/api/refine/run")

    assert response.status_code == 200
    assert response.json() == {
        "keep_count": 2,
        "refined": 1,
        "failed": 1,
        "upload_queued": False,
    }
    assert calls == [(videos_root, False, False)]


@pytest.mark.anyio
async def test_slice_options_accept_chat_context_120(videos_root, dashboard_client):
    async with dashboard_client(videos_root) as client:
        response = await client.post(
            "/api/slice/start",
            json={"slice_options": {"burst_context": 120}},
        )
    assert response.status_code != 400
