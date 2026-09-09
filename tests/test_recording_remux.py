import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.server import action_jobs, recording_remux
from src.maintenance import runtime_cleanup


def make_flv(make_room):
    source = make_room("8792912 - 咩栗") / "blive_8792912_2026-09-08-105557.flv"
    source.write_bytes(b"source" * 200000)
    return source


def test_completed_event_queue_is_idempotent_and_preserves_named_path(videos_root, make_room):
    source = make_flv(make_room)
    first = recording_remux.queue_completed_recording(videos_root, source)
    second = recording_remux.queue_completed_recording(videos_root, source)
    assert second["status"] == "already_pending"
    assert second["job"]["job_id"] == first["job"]["job_id"]
    assert first["job"]["payload"]["source_rel_path"] == source.relative_to(videos_root).as_posix()
    assert source.exists()
    with pytest.raises(ValueError):
        recording_remux.queue_completed_recording(videos_root, videos_root.parent / "outside.flv")


@pytest.mark.parametrize("valid", [True, False])
def test_worker_validates_before_deleting_source(videos_root, make_room, monkeypatch, valid):
    source = make_flv(make_room)
    source.with_suffix(".xml").write_text("<i/>")
    job = recording_remux.queue_completed_recording(videos_root, source)["job"]
    real_recover = runtime_cleanup.recover_recording

    def remux(src, output):
        assert src.exists()
        output.write_bytes(b"converted")
        return True

    def validate(path):
        assert source.exists()
        return {"valid": valid and path.name.endswith(".partial.mp4"), "error": "invalid"}

    monkeypatch.setattr(runtime_cleanup, "recover_recording", lambda src, **kwargs:
                        real_recover(src, **kwargs, validator=validate, remuxer=remux))
    assert action_jobs.process_action_jobs(videos_root) == int(valid)
    result = action_jobs.read_action_job(videos_root, job["job_id"])
    assert result["status"] == ("done" if valid else "failed")
    assert source.exists() is not valid
    assert source.with_suffix(".mp4").exists() is valid
    assert source.with_suffix(".xml").exists()
    assert not (videos_root / ".bilive-state").exists()  # remux is not source trash


@pytest.mark.anyio
async def test_recorder_hook_queues_only_postprocessing_complete_and_wakes_windows(
    videos_root, make_room, monkeypatch
):
    from fastapi import FastAPI
    from src.dashboard import remote_worker

    source = make_flv(make_room)
    subscribers = []
    disposed = []
    center = SimpleNamespace(events=SimpleNamespace(subscribe=lambda callback:
        (subscribers.append(callback) or SimpleNamespace(dispose=lambda: disposed.append(True)))))
    module = ModuleType("blrec.event.event_center")
    module.EventCenter = SimpleNamespace(get_instance=lambda: center)
    monkeypatch.setitem(sys.modules, "blrec.event.event_center", module)
    wakes = []
    monkeypatch.setattr(remote_worker, "trigger_remote_worker", lambda **kwargs:
                        (wakes.append(kwargs) or {"status": "accepted"}))
    app = FastAPI()
    recording_remux.install_recording_remux(app, videos_root)
    await app.router.startup()
    try:
        subscribers[0](SimpleNamespace(type="VideoFileCreatedEvent", data=SimpleNamespace(path=str(source))))
        assert not list(action_jobs.jobs_dir(videos_root).glob("*.pending.json"))
        subscribers[0](SimpleNamespace(type="VideoPostprocessingCompletedEvent", data=SimpleNamespace(path=str(source))))
        for _ in range(100):
            if wakes:
                break
            await asyncio.sleep(0.01)
        assert wakes == [{"pending_tasks": 1}]
        assert source.exists()
    finally:
        await app.router.shutdown()
    assert disposed == [True]
