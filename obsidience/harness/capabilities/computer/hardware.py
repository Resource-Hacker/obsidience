"""Adapter for ``computer.hardware``: this computer's current load, read-only."""

from __future__ import annotations

import json


def _gib(mib):
    return round(mib / 1024, 1) if isinstance(mib, (int, float)) else None


def execute(args: dict, context: dict) -> str:
    del args, context
    from obsidience.harness.host import monitor

    sample = monitor.snapshot()
    cpu, memory = sample.get("cpu") or {}, sample.get("memory") or {}
    gpus = []
    for gpu in sample.get("gpus") or []:
        row = {key: gpu.get(key) for key in (
            "device", "name", "status", "utilization_percent", "encoder_percent", "decoder_percent",
            "media_engine_percent", "temperature_c", "power_w", "power_limit_w", "pstate")
            if gpu.get(key) is not None}
        row["vram_free_gib"], row["vram_total_gib"] = _gib(gpu.get("memory_free_mib")), _gib(gpu.get("memory_total_mib"))
        gpus.append(row)
    total, available = memory.get("total_bytes"), memory.get("available_bytes")
    return json.dumps({
        "captured_at": sample.get("captured_at"),
        "cpu": {key: cpu.get(key) for key in ("name", "threads", "utilization_percent", "load_1m", "temperature_c")},
        "memory": {"total_gib": round(total / 2**30, 1) if total else None,
                   "available_gib": round(available / 2**30, 1) if available else None},
        "gpus": gpus,
        "problems": sample.get("problems") or [],
    }, ensure_ascii=False)
