"""Harness lifecycle of the shared, idle CPU text sensor; capture stays with Tools."""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import CONFIG
from .ocr import CpuOCR

_reader: CpuOCR | None = None
_lifecycle = threading.Lock()


def background_thread() -> None:
    """Only this dedicated worker and its new native threads inherit the policy."""
    cpus = CONFIG.extras.get("vision_ocr_cpus", [])
    if cpus:
        selected = set(cpus) & os.sched_getaffinity(0)
        if not selected:
            raise RuntimeError("No configured OCR CPUs are available")
        os.sched_setaffinity(0, selected)
    os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))


def start() -> None:
    """Called off the event loop before serving; optional models are local only."""
    with _lifecycle:
        global _reader
        if _reader is not None:
            return
        directory = CONFIG.extras.get("vision_ocr_model_directory")
        if not directory:
            return
        candidate = CpuOCR(Path(directory))
        try:
            with ThreadPoolExecutor(max_workers=1, initializer=background_thread,
                                    thread_name_prefix="ocr-warm") as pool:
                pool.submit(candidate.warm).result()
            _reader = candidate
            logging.getLogger(__name__).info("Regional OCR ready: CPU-only PP-OCRv6-small")
        except Exception as cause:
            candidate.close()
            logging.getLogger(__name__).warning("Regional OCR unavailable: %s", type(cause).__name__)


def reader() -> CpuOCR | None:
    return _reader


def close() -> None:
    with _lifecycle:
        global _reader
        previous, _reader = _reader, None
        if previous is not None:
            previous.close()
