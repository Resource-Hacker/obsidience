"""Bounded structured activation stream shared by every Task execution."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    pending: deque[dict] = field(default_factory=lambda: deque(maxlen=100))
    scheduled: bool = False

_HISTORY: deque[dict] = deque(maxlen=100)
_PLAYBACK: dict = {"status": "idle", "level": 0.0, "run_id": "", "playback_id": ""}
_SUBSCRIBERS: dict[asyncio.Queue, _Subscriber] = {}
_LOCK = threading.RLock()
MAX_REVIEW_LINKS = 64
MAX_REVIEW_REF_CHARS = 512


def _deliver(queue: asyncio.Queue) -> None:
    with _LOCK:
        subscriber = _SUBSCRIBERS.get(queue)
        if subscriber is None:
            return
        events = list(subscriber.pending)
        subscriber.pending.clear()
        subscriber.scheduled = False
    for event in events:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)


def _publish(event: dict, *, retain: bool = True) -> dict:
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    with _LOCK:
        if retain:
            _HISTORY.append(event)
        for queue, subscriber in tuple(_SUBSCRIBERS.items()):
            subscriber.pending.append(event)
            if subscriber.scheduled:
                continue
            if subscriber.loop is current_loop:
                _deliver(queue)
            else:
                # One callback and a bounded tail per subscriber, even while
                # its event loop is busy. Publication order matches history.
                subscriber.scheduled = True
                try:
                    subscriber.loop.call_soon_threadsafe(_deliver, queue)
                except RuntimeError:
                    # A disconnected presenter cannot fail a committed Review.
                    unsubscribe(queue)
    return event


def emit(phase: str, refs: list[str], *, query: str = "", graph_id: str = "main",
         retrieval_ms: float | None = None, run_id: str = "", turn_id: str = "") -> dict:
    unique_refs = list(dict.fromkeys(str(ref) for ref in refs if ref))
    event = {
        "phase": phase,
        "refs": unique_refs[:128],
        "ref_count": len(unique_refs), "omitted_refs": max(0, len(unique_refs)-128),
        "evidence_scope": "runtime_activity_not_hidden_reasoning",
        "query": str(query)[:300],
        "graph_id": str(graph_id or "main")[:80],
        "at": int(time.time() * 1000),
    }
    if run_id:
        event["run_id"] = str(run_id)[:128]
    if turn_id:
        event["turn_id"] = str(turn_id)[:128]
    if retrieval_ms is not None:
        event["retrieval_ms"] = max(0.0, float(retrieval_ms))
    return _publish(event)


def emit_playback(status: str, *, level: float = 0.0, run_id: str = "",
                  playback_id: str = "") -> dict:
    """Ephemeral speaker envelope, separate from the retained Thinking Packet."""
    global _PLAYBACK
    with _LOCK:
        _PLAYBACK = {
            "status": status, "level": level,
            "run_id": run_id, "playback_id": playback_id,
            "at": int(time.time() * 1000),
        }
        # Audio samples must never evict the packet needed on reconnect.
        return _publish({"type": "playback", "playback": dict(_PLAYBACK)}, retain=False)


def playback() -> dict:
    with _LOCK:
        return dict(_PLAYBACK)


def emit_review_change(proposal_id: str, run_id: str, state: str, *,
                       decided_at: float | None = None, links: list[dict] | None = None) -> dict | None:
    """Public Review projection; callers supply only validated owner outcomes."""
    if (state not in {"pending", "approved", "rejected"}
            or not isinstance(proposal_id, str) or not 0 < len(proposal_id) <= 512
            or not isinstance(run_id, str) or len(run_id) > 80):
        return None
    review = {"proposal_id": proposal_id, "run_id": run_id, "state": state, "truncated": False}
    if state != "pending":
        if (type(decided_at) not in (int, float)
                or not 0 <= decided_at <= (2**53 - 1) / 1000 or not math.isfinite(decided_at)):
            return None
        review["decided_at"] = int(decided_at * 1000)
    if state == "approved":
        pairs, seen = [], set()
        for item in links or []:
            if (not isinstance(item, dict) or any(not isinstance(item.get(key), str)
                    or not 0 < len(item[key]) <= MAX_REVIEW_REF_CHARS for key in ("source", "target"))):
                review["truncated"] = True
                continue
            pair = (item["source"], item["target"])
            if pair in seen or pair[0] == pair[1]:
                continue
            seen.add(pair)
            if len(pairs) == MAX_REVIEW_LINKS:
                review["truncated"] = True
                continue
            pairs.append({"source": pair[0], "target": pair[1]})
        review["links"] = pairs
    return _publish({"phase": "review_changed", "refs": [], "query": "", "graph_id": "main",
                     "at": int(time.time() * 1000), "review": review})


def history() -> list[dict]:
    with _LOCK:
        return list(_HISTORY)


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()
    with _LOCK:
        _SUBSCRIBERS[queue] = _Subscriber(loop)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    with _LOCK:
        _SUBSCRIBERS.pop(queue, None)
