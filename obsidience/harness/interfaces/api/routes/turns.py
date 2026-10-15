"""Completed external developer-agent turns handed to Executive memory."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/api/turns/complete")
async def completed_turn(payload: dict):
    """Queue a completed external turn through Obsidience's graph event Tasks."""
    user = payload.get("user")
    assistant = payload.get("assistant")
    thread_id = payload.get("thread_id")
    external_turn_id = payload.get("turn_id")
    if not all(isinstance(value, str) for value in (user, assistant, thread_id, external_turn_id)):
        raise HTTPException(400, "turn fields must be strings")
    if not user.strip() or not assistant.strip() or not thread_id or not external_turn_id:
        raise HTTPException(400, "completed turn is incomplete")
    from ....memory.hindsight import MEMORY, MAX_TURN_CHARS, MemoryContentTooLarge, MemoryDeliveryConflict
    if len(user) > MAX_TURN_CHARS or len(assistant) > MAX_TURN_CHARS:
        raise HTTPException(413, "completed turn exceeds the bounded handoff size")
    # The external developer agent that completed the turn; Codex is the
    # historical default, so existing Codex turn identities are unchanged.
    source = payload.get("source", "codex")
    if source not in {"codex", "claude-code"}:
        raise HTTPException(400, "unsupported completed-turn source")
    turn_id = hashlib.sha256(
        f"{source}\0{thread_id}\0{external_turn_id}".encode()
    ).hexdigest()[:24]
    timestamp = payload.get("timestamp")
    if timestamp is not None:
        from datetime import datetime
        try:
            if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
                raise ValueError("timezone required")
        except ValueError as cause:
            raise HTTPException(400, "timestamp must be an ISO date with timezone") from cause
    try:
        delivery = MEMORY.completed_status(
            "Agents/Executive/Executive", user, assistant, source=source,
            identifier=turn_id, timestamp=timestamp,
        )
    except MemoryContentTooLarge as cause:
        raise HTTPException(413, str(cause)) from cause
    except MemoryDeliveryConflict as cause:
        raise HTTPException(409, str(cause)) from cause
    except Exception as cause:
        # Never acknowledge a lost insert as an idempotent duplicate. The hook
        # remains fail-open for the coding agent and records this failed handoff.
        raise HTTPException(503, f"Memory delivery could not be recorded ({type(cause).__name__})") from cause
    return {
        "accepted": delivery != "disabled",
        "delivery_status": delivery,
        "queued_tasks": int(delivery == "inserted"),
        "raw_persisted": False,
        "turn_hash": turn_id,
    }
