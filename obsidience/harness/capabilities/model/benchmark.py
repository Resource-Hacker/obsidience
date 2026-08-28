"""Adapter for ``model.benchmark``."""

from __future__ import annotations

import json

import httpx


def execute(args: dict, context: dict) -> str:
    del context
    args = args or {}
    model_id = str(args.get("model_id", "")).strip()
    devices = args.get("devices")
    if not model_id or not isinstance(devices, list) or not devices:
        return "Model benchmark rejected: model_id and a nonempty devices list are required."
    try:
        with httpx.Client(timeout=1_800) as client:
            response = client.post(
                f"http://127.0.0.1:8765/api/models/{model_id}/benchmark",
                json={"devices": devices},
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as exc:
        return f"Model benchmark failed: {exc}."
    return json.dumps(result, sort_keys=True)
