"""Scheduler: one asyncio loop; cron for scheduled tasks, ready-queue for one-shots."""

from __future__ import annotations

import asyncio
import time

from croniter import croniter

from .config import CONFIG
from .executor import run_task
from .indexer import INDEX
from .vault import iter_notes

_running: set[str] = set()
_last_fired: dict[str, float] = {}


def due_tasks() -> list:
    now = time.time()
    due = []
    for note in iter_notes():
        if note.kind != "task" or note.ref in _running:
            continue
        status = str(note.meta.get("status", "draft"))
        schedule = note.meta.get("schedule")
        if schedule and status in ("pending", "completed", "review", "failed"):
            base = _last_fired.get(note.ref) or note.mtime
            try:
                nxt = croniter(str(schedule), base).get_next(float)
            except (ValueError, KeyError):
                continue
            if nxt <= now and status != "review":  # never re-fire past an unreviewed result
                due.append(note)
        elif not schedule and status == "pending":
            due.append(note)
    return due


async def _run(note) -> None:
    _running.add(note.ref)
    _last_fired[note.ref] = time.time()
    try:
        await run_task(note)
    finally:
        _running.discard(note.ref)


async def loop() -> None:
    sem = asyncio.Semaphore(CONFIG.concurrency)
    while True:
        try:
            INDEX.sync()
            for note in due_tasks():
                async def bounded(n=note):
                    async with sem:
                        await _run(n)
                asyncio.create_task(bounded())
        except Exception as exc:  # noqa: BLE001 — the tick must survive anything
            print(f"[scheduler] tick error: {exc}")
        await asyncio.sleep(CONFIG.tick_seconds)
