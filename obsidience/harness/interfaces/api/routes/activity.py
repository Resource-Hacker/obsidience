"""Execution presentation streams: the Action trace and Knowledge activity."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ....execution import activity as knowledge_activity
from ....execution import trace
from ..streams import serve_websocket_events

router = APIRouter()


@router.websocket("/ws/trace")
async def action_trace_ws(ws: WebSocket):
    await ws.accept()
    raw_cursor = ws.query_params.get("after")
    if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdecimal() or len(raw_cursor) > 16):
        await ws.close(code=1008, reason="Invalid trace cursor")
        return
    after = int(raw_cursor) if raw_cursor is not None else None
    queue = trace.subscribe()

    async def send_events():
        frame = trace.replay(after)
        cursor = frame["cursor"]
        await ws.send_json(frame)
        while True:
            entry = await queue.get()
            sequence = entry.get("seq")
            if sequence is not None and sequence <= cursor:
                continue
            if sequence is not None and sequence != cursor + 1:
                frame = trace.replay(cursor)
                await ws.send_json(frame)
                cursor = frame["cursor"]
            else:
                await ws.send_json({"type": "entry", "entry": entry, "cursor": sequence or cursor})
                cursor = sequence or cursor

    try:
        await serve_websocket_events(ws, send_events)
    finally:
        trace.unsubscribe(queue)


@router.websocket("/ws/activity")
async def knowledge_activity_ws(ws: WebSocket):
    """Every Task activation, independent of how the Task was started."""
    await ws.accept()
    queue = knowledge_activity.subscribe()

    async def send_events():
        await ws.send_json({"type": "snapshot", "entries": knowledge_activity.history(),
                            "playback": knowledge_activity.playback(),
                            "operations": knowledge_activity.operations()})
        while True:
            await ws.send_json({"type": "activity", **await queue.get()})

    try:
        await serve_websocket_events(ws, send_events)
    finally:
        knowledge_activity.unsubscribe(queue)
