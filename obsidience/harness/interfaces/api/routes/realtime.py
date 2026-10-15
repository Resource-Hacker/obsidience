"""Speech transport state, listening mode and its event stream."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket

from ....realtime import runtime as realtime
from ..streams import serve_websocket_events

router = APIRouter()


@router.get("/api/realtime")
def realtime_status():
    """Return speech transport state, independent of the selected work Task."""

    return realtime.RUNTIME.snapshot()


@router.patch("/api/realtime/mode")
async def realtime_mode(payload: dict):
    try:
        if "mode" in payload:
            return await realtime.RUNTIME.set_listening_mode(payload["mode"])
        return await realtime.RUNTIME.set_proactive(payload.get("proactive"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.websocket("/ws/realtime")
async def realtime_ws(ws: WebSocket):
    await ws.accept()
    queue = realtime.RUNTIME.subscribe()

    async def send_events():
        await ws.send_json({"type": "state", "state": realtime.RUNTIME.snapshot()})
        while True:
            await ws.send_json(await queue.get())

    try:
        await serve_websocket_events(ws, send_events)
    finally:
        realtime.RUNTIME.unsubscribe(queue)
