# Copyright (c) 2024 bilive.
"""Streamer profile and human-approved experience routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.dashboard._context import DashboardContext, get_context
from src.dashboard.source_lifecycle import (
    apply_streamer_recommendation,
    patch_streamer_profile,
    read_streamer_profile,
    read_streamer_recommendations,
    read_experiences,
    streamer_evidence_summary,
)


router = APIRouter()


def _profile_action(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/streamers/{room_id}/profile")
async def get_streamer_profile(
    room_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _profile_action(
        lambda: {
            "profile": read_streamer_profile(ctx.store.videos_root, room_id),
            "recommendations": read_streamer_recommendations(
                ctx.store.videos_root,
                room_id,
            ),
            "evidence": streamer_evidence_summary(
                ctx.store.videos_root,
                room_id,
            ),
        }
    )


@router.patch("/api/streamers/{room_id}/profile")
async def update_streamer_profile(
    room_id: str,
    payload: Dict[str, Any],
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _profile_action(
        lambda: {
            "profile": patch_streamer_profile(
                ctx.store.videos_root,
                room_id,
                payload,
            ),
            "recommendations": read_streamer_recommendations(
                ctx.store.videos_root,
                room_id,
            ),
            "evidence": streamer_evidence_summary(
                ctx.store.videos_root,
                room_id,
            ),
        }
    )


@router.get("/api/streamers/{room_id}/experiences")
async def get_streamer_experiences(
    room_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> list[dict[str, Any]]:
    return _profile_action(
        lambda: read_experiences(ctx.store.videos_root, room_id=room_id)
    )


@router.post("/api/streamers/{room_id}/recommendations/{recommendation_id}/apply")
async def apply_streamer_recommendation_api(
    room_id: str,
    recommendation_id: str,
    ctx: DashboardContext = Depends(get_context),
) -> Dict[str, Any]:
    return _profile_action(
        lambda: apply_streamer_recommendation(
            ctx.store.videos_root,
            room_id,
            recommendation_id,
        )
    )
