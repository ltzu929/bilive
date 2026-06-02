"""Tests for extended worker_status() and recovery actions."""

import json
import time

import pytest
import httpx

from src.dashboard.app import create_app
from src.server import worker_control


# ── worker_status() extension tests ──

def test_worker_status_returns_idle_when_no_process():
    worker_control._worker_process = None
    status = worker_control.worker_status()
    assert status["status"] == "idle"


def test_worker_status_returns_running_with_metadata():
    worker_control._worker_process = None
    # Simulate that start_worker_once stored metadata
    worker_control._worker_started_at = 1700000000.0
    worker_control._worker_command = ["python", "-m", "src.server.watcher", "--once"]
    worker_control._worker_log_path = "logs/runtime/pc-worker-test.log"

    status = worker_control.worker_status()
    assert status["status"] == "idle"
    # Metadata should be available even when idle (last run info)
    assert status.get("last_started_at") == 1700000000.0
    assert status.get("last_command") == ["python", "-m", "src.server.watcher", "--once"]
    assert status.get("last_log_path") == "logs/runtime/pc-worker-test.log"


# ── Recovery action tests ──

@pytest.mark.anyio
async def test_requeue_removes_done_and_writes_pending(tmp_path):
    """POST /api/tasks/{task_id}/requeue removes .done and writes .pending."""
    from src.dashboard.slice_control import load_pending_queue_state

    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")

    # Encode relative path as task_id (base64 of rel path, matching file_store pattern)
    import base64
    task_id = base64.urlsafe_b64encode(
        "22384516/22384516_20260527-12-55-32.mp4".encode()
    ).decode().rstrip("=")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task_id}/requeue")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "requeued"

    # .done should be removed, .pending should exist
    assert not source.with_suffix(".mp4.done").exists()
    assert source.with_suffix(".mp4.pending").exists()

    pending_state = load_pending_queue_state(videos)
    assert pending_state["pending_tasks"] == 1


@pytest.mark.anyio
async def test_cancel_pending_removes_pending_marker(tmp_path):
    """POST /api/tasks/{task_id}/cancel-pending removes .pending."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    import base64
    task_id = base64.urlsafe_b64encode(
        "22384516/22384516_20260527-12-55-32.mp4".encode()
    ).decode().rstrip("=")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task_id}/cancel-pending")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert not source.with_suffix(".mp4.pending").exists()
    assert source.exists()  # Source .mp4 preserved
    assert source.with_suffix(".xml").exists()  # XML preserved


@pytest.mark.anyio
async def test_mark_done_writes_done_without_slicing(tmp_path):
    """POST /api/tasks/{task_id}/mark-done writes .done."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")

    import base64
    task_id = base64.urlsafe_b64encode(
        "22384516/22384516_20260527-12-55-32.mp4".encode()
    ).decode().rstrip("=")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task_id}/mark-done")

    assert response.status_code == 200
    assert response.json()["status"] == "marked_done"
    assert source.with_suffix(".mp4.done").exists()


@pytest.mark.anyio
async def test_mark_done_removes_existing_pending_marker(tmp_path):
    """Manual mark-done also removes queued pending work for the same source."""
    videos = tmp_path / "Videos"
    room = videos / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260527-12-55-32.mp4"
    source.write_bytes(b"video data")
    source.with_suffix(".xml").write_text("<danmaku/>", encoding="utf-8")
    source.with_suffix(".mp4.pending").write_text("{}", encoding="utf-8")

    import base64
    task_id = base64.urlsafe_b64encode(
        "22384516/22384516_20260527-12-55-32.mp4".encode()
    ).decode().rstrip("=")

    transport = httpx.ASGITransport(app=create_app(videos_root=videos))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/tasks/{task_id}/mark-done")

    assert response.status_code == 200
    assert source.with_suffix(".mp4.done").exists()
    assert not source.with_suffix(".mp4.pending").exists()


@pytest.mark.anyio
async def test_recovery_endpoints_reject_invalid_task_id(tmp_path):
    """Invalid task IDs return 404 or 400."""
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tasks/bad_id/requeue")
        assert resp.status_code in (400, 404)


@pytest.mark.anyio
async def test_recovery_endpoints_reject_path_traversal(tmp_path):
    """Task IDs that resolve outside Videos/ are rejected."""
    import base64
    task_id = base64.urlsafe_b64encode("../etc/passwd".encode()).decode().rstrip("=")
    transport = httpx.ASGITransport(app=create_app(videos_root=tmp_path / "Videos"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/tasks/{task_id}/requeue")
        assert resp.status_code in (400, 404)
