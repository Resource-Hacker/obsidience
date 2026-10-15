"""Lifetime of one server-to-client presentation WebSocket."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect


async def serve_websocket_events(ws: WebSocket, send_events):
    """Join both halves of a presentation stream on disconnect or cancellation."""
    async def receive_disconnect():
        while True:
            if (await ws.receive())["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(send_events()), asyncio.create_task(receive_disconnect())]
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
