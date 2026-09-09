"""Hand completed recorder FLVs to the existing Windows action queue."""

import asyncio
import base64
import logging
from contextlib import suppress
from pathlib import Path

from src.recording_paths import room_identity
from src.server.action_jobs import enqueue_action_job, jobs_dir

logger = logging.getLogger(__name__)


def queue_completed_recording(videos_root, source_path):
    root = Path(videos_root).resolve()
    source = Path(source_path).resolve()
    relative = source.relative_to(root)
    if source.suffix != ".flv" or not room_identity(source.parent)[0]:
        return None
    if source.stem.endswith("_injecting"):
        return None
    if not source.is_file():
        return None
    identifier = base64.urlsafe_b64encode(relative.as_posix().encode()).decode().rstrip("=")
    return enqueue_action_job(root, action="remux_recording", recording_id=identifier,
                              payload={"source_rel_path": relative.as_posix()})


def remux_completed_recording(videos_root, payload):
    from src.maintenance.runtime_cleanup import recover_recording, validate_media

    root = Path(videos_root).resolve()
    source = (root / payload["source_rel_path"]).resolve()
    source.relative_to(root)
    if source.suffix != ".flv" or not room_identity(source.parent)[0]:
        raise ValueError("Invalid completed recording")
    if not source.exists():
        if validate_media(source.with_suffix(".mp4")).get("valid"):
            return {"status": "already_remuxed"}
        raise FileNotFoundError(source)
    result = recover_recording(source, execute=True)
    if result["status"] not in {"recovered", "kept_existing_mp4"}:
        raise RuntimeError(f"Remux failed; FLV preserved: {result['validation'].get('error', '')}")
    return result


def install_recording_remux(app, videos_root):
    from blrec.event.event_center import EventCenter
    from src.dashboard.remote_worker import trigger_remote_worker

    root = Path(videos_root).resolve()
    wake = asyncio.Event()
    subscription = None
    worker_task = None

    def on_event(event):
        if event.type != "VideoPostprocessingCompletedEvent":
            return
        try:
            if queue_completed_recording(root, event.data.path):
                wake.set()
        except Exception:
            logger.exception("Unable to queue completed FLV; source preserved")

    async def dispatch():
        # Windows may be off overnight. Persisted jobs must resume when it returns.
        while True:
            wake.clear()
            pending = []
            for path in jobs_dir(root).glob("*.pending.json"):
                import json
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if job.get("action") == "remux_recording":
                    pending.append(path)
            if pending:
                result = await asyncio.to_thread(trigger_remote_worker, pending_tasks=len(pending))
                if result.get("status") in {"failed", "disabled"}:
                    logger.warning("Recording remux remains pending: %s", result.get("status"))
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=60)

    async def start():
        nonlocal subscription, worker_task
        subscription = EventCenter.get_instance().events.subscribe(on_event)
        worker_task = asyncio.create_task(dispatch())

    async def stop():
        if subscription is not None:
            subscription.dispose()
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    app.add_event_handler("startup", start)
    app.add_event_handler("shutdown", stop)
