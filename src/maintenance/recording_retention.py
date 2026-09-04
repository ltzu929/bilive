"""Schedule and execute safe source-recording retention actions on Windows."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any

from src.dashboard.recording_trash import build_trash_plan
from src.dashboard.source_lifecycle import (
    RecordingTrashBlocked,
    get_recording_state,
    mutate_recording_state,
    recording_state_path,
    retention_fields,
    set_review_state,
    set_trash_job_state,
)
from src.dashboard.task_state import build_task_inventory
from src.server.action_jobs import (
    enqueue_action_job,
    find_active_recording_job,
)


def maintain_recording_retention(
    videos_root: str | Path,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Warn at day 11 and enqueue day-14 recycle-bin actions.

    The maintenance pass never moves files itself. It creates the same
    Windows-only ``trash_recording`` action for the normal worker to consume.
    It deliberately does not execute or wake that worker, so a maintenance pass
    cannot make unrelated pending actions run.
    """
    root = Path(videos_root).expanduser().resolve()
    current_time = time.time() if now is None else float(now)
    warnings: list[dict[str, Any]] = []
    scheduled: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    tasks = build_task_inventory(root)

    for task in tasks:
        task_id = str(task.get("task_id") or "")
        source_rel_path = str(task.get("source_rel_path") or "")
        room_id = str(task.get("room_id") or "")
        state = _ensure_state(
            root,
            task_id,
            source_rel_path=source_rel_path,
            room_id=room_id,
            recorded_at=str(task.get("recorded_at") or ""),
        )
        fields = retention_fields(
            state,
            now=current_time,
            source_exists=(root / source_rel_path).is_file(),
        )
        if fields["retention_warning"] and not fields["retention_expired"]:
            warnings.append(
                {
                    "task_id": task_id,
                    "retention_deadline": fields["retention_deadline"],
                    "message": "录播未完成复核，已进入第 11 天保留预警",
                }
            )
        if not fields["retention_expired"] or str(state.get("trash_status") or "") == "done":
            continue

        active = find_active_recording_job(root, task_id)
        if active is not None:
            reason = "trash_action_active"
            set_trash_job_state(
                root,
                task_id,
                status="blocked",
                job_id=str(active.get("job_id") or ""),
                reason=reason,
            )
            blocked.append(
                {
                    "task_id": task_id,
                    "reason": reason,
                    "job_id": str(active.get("job_id") or ""),
                }
            )
            continue

        try:
            plan = build_trash_plan(
                root,
                task_id,
                payload={"force_expired": True},
                now=current_time,
            )
        except RecordingTrashBlocked as exc:
            reason = _blocking_reason(exc)
            set_trash_job_state(root, task_id, status="blocked", reason=reason)
            blocked.append({"task_id": task_id, "reason": reason})
            continue

        if plan.get("status") != "ready":
            reason = "源录播回收计划未就绪"
            set_trash_job_state(root, task_id, status="blocked", reason=reason)
            blocked.append({"task_id": task_id, "reason": reason})
            continue

        result = enqueue_action_job(
            root,
            action="trash_recording",
            recording_id=task_id,
            payload={"force_expired": True},
        )
        job = result.get("job") or {}
        job_id = str(job.get("job_id") or "")
        set_review_state(
            root,
            task_id,
            "trash_pending",
            source_rel_path=source_rel_path,
            room_id=room_id,
            recorded_at=str(task.get("recorded_at") or ""),
        )
        set_trash_job_state(root, task_id, status="pending", job_id=job_id)
        scheduled.append(
            {
                "task_id": task_id,
                "job_id": job_id,
                "status": result.get("status"),
                "files": list(plan.get("files") or []),
            }
        )

    return {
        "status": "ok",
        "warnings": warnings,
        "scheduled": scheduled,
        "blocked": blocked,
    }


def _ensure_state(
    root: Path,
    task_id: str,
    *,
    source_rel_path: str,
    room_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    current = get_recording_state(
        root,
        task_id,
        source_rel_path=source_rel_path,
        room_id=room_id,
        recorded_at=recorded_at,
    )
    if recording_state_path(root, task_id).is_file():
        return current
    return mutate_recording_state(
        root,
        task_id,
        lambda state: state,
        source_rel_path=source_rel_path,
        room_id=room_id,
        recorded_at=recorded_at,
    )


def _blocking_reason(exc: Exception) -> str:
    blockers = getattr(exc, "blockers", None)
    if blockers:
        return "; ".join(str(item) for item in blockers)
    return str(exc) or type(exc).__name__


def _default_videos_root() -> Path:
    configured = os.environ.get("BILIVE_VIDEOS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "Videos"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bilive recording retention maintenance")
    parser.add_argument("--videos-root", default=str(_default_videos_root()))
    args = parser.parse_args(argv)
    result = maintain_recording_retention(args.videos_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result["blocked"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
