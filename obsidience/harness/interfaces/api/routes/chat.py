"""The one persisted Executive conversation, projected into every Chat pane."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ....conversation import runtime as conversation_runtime
from ....conversation.store import CONVERSATION
from ....realtime import runtime as realtime

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    """Project the one persisted Executive conversation into every Chat pane."""
    await ws.accept()
    queue = CONVERSATION.subscribe()
    queue.put_nowait(conversation_runtime.RUNTIME.active_turn())

    async def send_events() -> None:
        # Deliver the conversation immediately, even if tokenization is cold.
        while not queue.empty():
            await ws.send_json(queue.get_nowait())
        queue.put_nowait(await conversation_runtime.RUNTIME.context_status())
        while True:
            await ws.send_json(await queue.get())

    async def receive_requests() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "steer":
                try:
                    result = await conversation_runtime.RUNTIME.steer(
                        str(msg.get("text", "")), expected_turn_id=str(msg.get("expected_turn_id", "")),
                    )
                    queue.put_nowait({"type": "steering", **result})
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            if msg.get("type") == "new_conversation":
                try:
                    await conversation_runtime.RUNTIME.new_conversation(
                        defer=realtime.RUNTIME.scheduler_paused(),
                    )
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                await conversation_runtime.RUNTIME.submit(
                    text, source="text", wait=False,
                    memory_writeback=msg.get("memory_writeback") is not False)
            except (ValueError, RuntimeError) as exc:
                queue.put_nowait({"type": "error", "text": str(exc)[:512]})

    sender = asyncio.create_task(send_events(), name="obsidience-chat-send")
    receiver = asyncio.create_task(receive_requests(), name="obsidience-chat-receive")
    try:
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            try:
                task.result()
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        CONVERSATION.unsubscribe(queue)
