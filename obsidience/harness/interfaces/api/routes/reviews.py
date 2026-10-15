"""Owner Review: staged proposals and their decisions."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from ....knowledge import review

router = APIRouter()
_REVIEW_LOCK = threading.RLock()


@router.post("/api/proposals")
def stage_proposal(payload: dict):
    """Local Codex/agent boundary for one ordinary owner-review proposal."""
    from ....knowledge.proposals import stage_proposal as stage

    try:
        return stage(
            payload,
            {"agent": "Codex", "task": "codex:knowledge-handoff"},
        )
    except ValueError as cause:
        raise HTTPException(400, str(cause)) from cause


@router.get("/api/reviews")
def reviews():
    with _REVIEW_LOCK:
        return review.list_reviews()


@router.post("/api/reviews/{name}/acknowledge")
def acknowledge_review(name: str):
    try:
        with _REVIEW_LOCK:
            return review.acknowledge_notification(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/api/reviews/{name}/approve")
def approve(name: str):
    try:
        with _REVIEW_LOCK:
            return review.approve(name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/reviews/{name}/reject")
def reject(name: str, reason: str = ""):
    try:
        with _REVIEW_LOCK:
            return review.reject(name, reason)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
