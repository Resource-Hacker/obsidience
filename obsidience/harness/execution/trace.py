"""Bounded live Executive trace for Task actions."""

from __future__ import annotations

import asyncio
import time
from collections import deque

_HISTORY: deque[dict] = deque(maxlen=500)
_SUBSCRIBERS: set[asyncio.Queue] = set()


def emit(channel: str, line: str, detail: list[str] | None = None) -> None:
    entry = {
        "at": int(time.time() * 1000),
        "channel": str(channel)[:24],
        "line": str(line).replace("\n", " ")[:300],
        "detail": [str(item)[:500] for item in (detail or [])[:12]],
    }
    _HISTORY.append(entry)
    for queue in tuple(_SUBSCRIBERS):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(entry)


def history() -> list[dict]:
    return list(_HISTORY)


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _SUBSCRIBERS.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _SUBSCRIBERS.discard(queue)
