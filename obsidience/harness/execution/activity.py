"""Bounded structured activation stream shared by every Task execution."""

from __future__ import annotations

import asyncio
import time
from collections import deque

_HISTORY: deque[dict] = deque(maxlen=100)
_SUBSCRIBERS: set[asyncio.Queue] = set()


def emit(phase: str, refs: list[str], *, query: str = "", graph_id: str = "main",
         retrieval_ms: float | None = None) -> dict:
    event = {
        "phase": phase,
        "refs": list(dict.fromkeys(str(ref) for ref in refs if ref))[:32],
        "query": str(query)[:300],
        "graph_id": str(graph_id or "main")[:80],
        "at": int(time.time() * 1000),
    }
    if retrieval_ms is not None:
        event["retrieval_ms"] = max(0.0, float(retrieval_ms))
    _HISTORY.append(event)
    for queue in tuple(_SUBSCRIBERS):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)
    return event


def history() -> list[dict]:
    return list(_HISTORY)


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _SUBSCRIBERS.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _SUBSCRIBERS.discard(queue)
