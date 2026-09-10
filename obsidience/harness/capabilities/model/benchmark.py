"""Adapter for ``model.benchmark``."""

from __future__ import annotations

import json

import httpx

from obsidience.harness.models import runtime as model_runtime


async def execute(args: dict, context: dict) -> str:
    args = args or {}
    model_id = str(args.get("model_id", "")).strip()
    devices = args.get("devices")
    if not model_id or not isinstance(devices, list) or not devices:
        return "Model benchmark rejected: model_id and a nonempty devices list are required."
    try:
        result = await model_runtime.benchmark(model_id, devices)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        return f"Model benchmark failed: {exc}."
    result = dict(result)
    if result.pop("cancellation_requested", False) is True:
        context["_capability_cancelled_after_commit"] = True
    return json.dumps(result, sort_keys=True)
