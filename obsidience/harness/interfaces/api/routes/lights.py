"""Owner-local light visualizer control and bounded lifecycle cleanup."""
from __future__ import annotations

import asyncio
import contextlib
import threading

from fastapi import APIRouter, HTTPException

from ....capabilities.lights import calibration, visualize

router = APIRouter()
_stop_task = None


@router.get("/api/lights/visualizer")
def status():
    return visualize.status()


@router.get("/api/lights/visualizer/sources")
def sources():
    try:
        return {"sources": visualize.sources()}
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, "Audio graph unavailable") from exc


@router.get("/api/lights/visualizer/calibration")
def calibration_status():
    return calibration.status()


@router.post("/api/lights/visualizer/calibration")
async def measure_flashes(payload: dict | None = None):
    payload = payload or {}
    if set(payload) - {"fixtures"} or ("fixtures" in payload and (not isinstance(payload["fixtures"], list) or not all(isinstance(name, str) for name in payload["fixtures"]))):
        raise HTTPException(400, "Choose registered fixture names")
    cancel = threading.Event()
    pending = asyncio.create_task(asyncio.to_thread(calibration.measure, cancel, payload.get("fixtures")))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        cancel.set()
        calibration.cancel()
        with contextlib.suppress(Exception):
            await asyncio.shield(pending)
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/lights/visualizer")
async def control(payload: dict):
    cancel = threading.Event()
    pending = asyncio.create_task(asyncio.to_thread(visualize.control, payload, cancel))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        cancel.set()
        # Drain the same transaction and its rollback; never leave a request
        # cancellation free to finish starting an unobserved background effect.
        with contextlib.suppress(Exception):
            await asyncio.shield(pending)
        await asyncio.shield(asyncio.to_thread(visualize.stop))
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


async def open_lifecycle(realtime):
    global _stop_task
    queue = realtime.subscribe()

    async def follow_stop():
        try:
            while True:
                event = await queue.get()
                if event.get("reason") in {"stop_requested", "stopped"}:
                    await asyncio.to_thread(visualize.stop)
        finally:
            realtime.unsubscribe(queue)

    _stop_task = asyncio.create_task(follow_stop(), name="lights-visualizer-stop")


async def close_lifecycle():
    global _stop_task
    task, _stop_task = _stop_task, None
    if task:
        task.cancel()
        try:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            await asyncio.to_thread(visualize.stop)
    else:
        await asyncio.to_thread(visualize.stop)
