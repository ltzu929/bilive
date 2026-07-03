import pytest

from src.burn.task_history import write_task_history


def _write_recording(room, name, *, done=False, segments=None):
    source = room / name
    source.write_bytes(b"video")
    source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
    if done:
        source.with_suffix(".mp4.done").write_text("{}", encoding="utf-8")
    if segments is not None:
        write_task_history(
            source,
            status="done" if done else "ready",
            videos_root=room.parent,
            segments=segments,
        )
    return source


def test_build_eagle_source_index_uses_live_cover_url(
    videos_root,
    make_room,
    monkeypatch,
):
    from src.dashboard import eagle_index

    room = make_room("22384516")
    _write_recording(room, "22384516_20260602-12-56-49.mp4")
    eagle_index._cover_cache.clear()
    monkeypatch.setattr(
        eagle_index,
        "fetch_live_room_cover",
        lambda room_id: "https://i0.hdslb.com/bfs/live-cover.jpg",
    )

    items = eagle_index.build_eagle_source_index(videos_root)

    assert items[0]["thumbnail_url"] == "https://i0.hdslb.com/bfs/live-cover.jpg"


@pytest.mark.anyio
async def test_eagle_source_recordings_api_returns_lightweight_index(
    videos_root,
    make_room,
    dashboard_client,
    monkeypatch,
):
    from src.dashboard import eagle_index

    eagle_index._cover_cache.clear()
    monkeypatch.setattr(eagle_index, "fetch_live_room_cover", lambda room_id: "")
    room = make_room("22384516")
    source = _write_recording(
        room,
        "22384516_20260602-12-56-49.mp4",
        done=True,
        segments=[
            {"segment_id": "keep", "judge_status": "keep"},
            {"segment_id": "failed", "judge_status": "judge_failed"},
            {"segment_id": "review", "judge_status": "review"},
        ],
    )

    async with dashboard_client(videos_root) as client:
        response = await client.get("/api/eagle/source-recordings")

    assert response.status_code == 200
    # The Eagle endpoint must not publish a CORS wildcard header: the dashboard
    # is LAN-reachable and the index exposes room ids / source paths / cover
    # URLs, so a wildcard would let any same-LAN web page read the JSON.
    assert "access-control-allow-origin" not in response.headers
    assert response.json() == [
        {
            "source_task_id": "MjIzODQ1MTYvMjIzODQ1MTZfMjAyNjA2MDItMTItNTYtNDkubXA0",
            "source_rel_path": "22384516/22384516_20260602-12-56-49.mp4",
            "source_name": source.name,
            "room_id": "22384516",
            "room_name": "22384516",
            "recorded_at": "2026-06-02 12:56:49",
            "source_size_mb": 0.0,
            "status": "done",
            "segment_count": 3,
            "review_count": 2,
            "keep_count": 1,
            "thumbnail_url": "",
            "workspace_url": "/tasks?source_task_id=MjIzODQ1MTYvMjIzODQ1MTZfMjAyNjA2MDItMTItNTYtNDkubXA0",
        }
    ]


@pytest.mark.anyio
async def test_eagle_source_recordings_api_mirrors_current_existing_sources(
    videos_root,
    make_room,
    dashboard_client,
    monkeypatch,
):
    from src.dashboard import eagle_index

    eagle_index._cover_cache.clear()
    monkeypatch.setattr(eagle_index, "fetch_live_room_cover", lambda room_id: "")
    room = make_room("22384516")
    deleted = _write_recording(room, "22384516_20260602-12-56-49.mp4")
    retained = _write_recording(room, "22384516_20260603-12-56-49.mp4")

    async with dashboard_client(videos_root) as client:
        before = await client.get("/api/eagle/source-recordings")
        deleted.unlink()
        after = await client.get("/api/eagle/source-recordings")

    assert before.status_code == 200
    assert sorted(item["source_name"] for item in before.json()) == [
        deleted.name,
        retained.name,
    ]
    assert after.status_code == 200
    assert [item["source_name"] for item in after.json()] == [retained.name]
