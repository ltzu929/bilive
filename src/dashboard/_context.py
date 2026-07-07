# Copyright (c) 2024 bilive.
"""Per-app shared state for the dashboard.

``create_app`` builds a :class:`DashboardContext` and stores it on
``app.state.ctx``; route modules read it back via the :func:`get_context`
dependency. Keeping the optional hooks + the derived worker/segment helpers in
one object avoids recreating closures inside ``create_app`` and lets the route
files stay flat functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from fastapi import HTTPException, Request

from src.dashboard.file_store import DashboardFileStore
from src.server.action_jobs import enqueue_action_job
from src.dashboard.remote_worker import (
    remote_worker_status,
    stop_remote_worker,
    trigger_remote_worker,
    wake_remote_worker,
)
from src.dashboard.slice_control import start_slice_scan


_ALLOWED_SLICE_OPTIONS = {
    "burst_ratio",
    "burst_window",
    "burst_context",
    "burst_merge_gap",
    "burst_top_n",
}


@dataclass
class DashboardContext:
    store: DashboardFileStore
    slice_starter: Callable[..., Any] | None = None
    remote_worker_trigger: Callable[..., Any] | None = None
    remote_worker_status_reader: Callable[..., Any] | None = None
    remote_worker_waker: Callable[..., Any] | None = None
    remote_worker_stopper: Callable[..., Any] | None = None

    # ── remote worker helpers ────────────────────────────────────────────
    def trigger_worker(self, pending_tasks: int) -> Dict[str, Any]:
        if self.remote_worker_trigger is not None:
            return self.remote_worker_trigger(pending_tasks)
        return trigger_remote_worker(pending_tasks=pending_tasks)

    def read_worker_trigger_status(self) -> Dict[str, Any]:
        if self.remote_worker_status_reader is not None:
            return self.remote_worker_status_reader()
        return remote_worker_status()

    def wake_worker(self) -> Dict[str, Any]:
        if self.remote_worker_waker is not None:
            return self.remote_worker_waker()
        return wake_remote_worker()

    def stop_worker(self) -> Dict[str, Any]:
        if self.remote_worker_stopper is not None:
            return self.remote_worker_stopper()
        return stop_remote_worker()

    # ── slice helpers ────────────────────────────────────────────────────
    def start_slicing(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if self.slice_starter is not None:
            if payload:
                return self.slice_starter(payload)
            return self.slice_starter()
        slice_options = _validated_slice_options(payload)
        task_id = None
        if payload:
            raw_task_id = payload.get("task_id")
            if raw_task_id is not None:
                if not isinstance(raw_task_id, str):
                    raise HTTPException(status_code=400, detail="task_id must be a string")
                task_id = raw_task_id.strip()
                if not task_id:
                    raise HTTPException(status_code=400, detail="task_id must not be empty")
        return start_slice_scan(
            self.store.videos_root,
            slice_options=slice_options,
            task_id=task_id,
        )

    def queue_segment_action(self, action: str, segment_id: str) -> Dict[str, Any]:
        result = enqueue_action_job(
            self.store.videos_root,
            action=action,
            segment_id=segment_id,
        )
        result["status_url"] = f"/api/jobs/{result['job']['job_id']}"
        result["worker_trigger"] = self.trigger_worker(1)
        return result


def _validated_slice_options(payload: Dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be an object")
    opts = payload.get("slice_options")
    if opts is None:
        return None
    if not isinstance(opts, dict):
        raise HTTPException(status_code=400, detail="slice_options must be an object")
    unknown = sorted(set(opts) - _ALLOWED_SLICE_OPTIONS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown slice_options: {', '.join(unknown)}")

    def _float_option(name: str, minimum: float, maximum: float) -> float | None:
        if name not in opts:
            return None
        try:
            value = float(opts[name])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{name} must be numeric") from exc
        if not minimum <= value <= maximum:
            raise HTTPException(status_code=400, detail=f"{name} must be {minimum}-{maximum}")
        return value

    def _int_option(name: str, minimum: int, maximum: int) -> int | None:
        if name not in opts:
            return None
        try:
            value = int(opts[name])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise HTTPException(status_code=400, detail=f"{name} must be {minimum}-{maximum}")
        return value

    validated: dict[str, Any] = {}
    ratio = _float_option("burst_ratio", 1.5, 8.0)
    if ratio is not None:
        validated["burst_ratio"] = ratio

    for name, minimum, maximum in [
        ("burst_window", 5, 30),
        ("burst_merge_gap", 0, 30),
        ("burst_top_n", 1, 5),
    ]:
        value = _int_option(name, minimum, maximum)
        if value is not None:
            validated[name] = value

    if "burst_context" in opts:
        context = _int_option("burst_context", 30, 120)
        if context not in (30, 45, 60, 90, 120):
            raise HTTPException(status_code=400, detail="burst_context must be 30/45/60/90/120")
        validated["burst_context"] = context
    return validated if validated else None


def get_context(request: Request) -> DashboardContext:
    """FastAPI dependency: return the per-app ``DashboardContext``."""
    return request.app.state.ctx  # type: ignore[no-any-return]