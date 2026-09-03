from src.burn.task_history import write_task_history

import pytest


def _recording(videos_root, *, segments=None):
    room = videos_root / "22384516"
    room.mkdir(parents=True)
    source = room / "22384516_20260602-12-56-49.mp4"
    source.write_bytes(b"source")
    source.with_suffix(".xml").write_text("<i/>", encoding="utf-8")
    source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    write_task_history(
        source,
        status="done",
        videos_root=videos_root,
        segments=list(segments or []),
    )
    return source


@pytest.mark.anyio
async def test_source_recording_api_requires_explicit_empty_review_and_queues_trash(
    tmp_path,
    dashboard_client,
):
    videos = tmp_path / "Videos"
    _recording(videos)
    trigger_calls = []

    async with dashboard_client(
        videos,
        remote_worker_trigger=lambda pending: trigger_calls.append(pending)
        or {"status": "accepted", "pending": pending},
    ) as client:
        listing = await client.get("/api/source-recordings")
        task_id = listing.json()[0]["task_id"]
        incomplete = await client.post(
            f"/api/source-recordings/{task_id}/review-complete",
            json={},
        )
        completed = await client.post(
            f"/api/source-recordings/{task_id}/review-complete",
            json={"confirmed_no_content": True},
        )

    assert listing.status_code == 200
    assert {
        "review_state",
        "retention_deadline",
        "retention_warning",
        "trash_eligible",
    }.issubset(listing.json()[0])
    assert incomplete.status_code == 409
    assert "零候选" in incomplete.json()["detail"]
    assert completed.status_code == 200
    body = completed.json()
    assert body["review_state"] == "trash_pending"
    assert body["trash_job"]["status"] == "accepted"
    assert trigger_calls == [1]


@pytest.mark.anyio
async def test_missed_segment_api_persists_reason_and_queues_windows_action(
    tmp_path,
    dashboard_client,
):
    videos = tmp_path / "Videos"
    _recording(videos)

    async with dashboard_client(
        videos,
        remote_worker_trigger=lambda pending: {"status": "accepted"},
    ) as client:
        task_id = (await client.get("/api/source-recordings")).json()[0]["task_id"]
        response = await client.post(
            f"/api/source-recordings/{task_id}/missed-segments",
            json={
                "start_seconds": 10,
                "end_seconds": 30,
                "reason": "mimo_missed",
                "note": "完整落点未被自动候选覆盖",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["job"]["action"] == "create_missed_segment"
    assert body["segment"]["manual_origin"] == "missed_segment"
    assert body["segment"]["missed_reason"] == "mimo_missed"
    assert body["segment"]["review_note"] == "完整落点未被自动候选覆盖"
    assert body["segment"]["action_state"]["status"] == "pending"


@pytest.mark.anyio
async def test_streamer_profile_api_is_room_scoped(tmp_path, dashboard_client):
    videos = tmp_path / "Videos"
    _recording(videos)

    async with dashboard_client(videos) as client:
        updated = await client.patch(
            "/api/streamers/22384516/profile",
            json={
                "display_name": "主播 A",
                "default_tags": ["A风格"],
                "approved_guidance": "保留完整落点",
            },
        )
        profile = await client.get("/api/streamers/22384516/profile")
        other = await client.get("/api/streamers/22966160/profile")

    assert updated.status_code == 200
    assert profile.json()["profile"]["display_name"] == "主播 A"
    assert profile.json()["profile"]["default_tags"] == ["A风格"]
    assert other.json()["profile"]["default_tags"] == []
