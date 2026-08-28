"""Adapter for ``model.configure``."""

from __future__ import annotations

import json

import httpx


def execute(args: dict, context: dict) -> str:
    del context
    args = args or {}
    model_id = str(args.get("model_id", "")).strip()
    allowed = {
        "allowed_devices", "context_tokens", "max_output_tokens",
        "gpu_memory_utilization", "max_num_seqs",
    }
    payload = {key: args[key] for key in allowed if key in args}
    if not model_id or not payload:
        return "Model configuration rejected: model_id and at least one setting are required."
    try:
        with httpx.Client(timeout=1_200) as client:
            response = client.patch(
                f"http://127.0.0.1:8765/api/models/{model_id}",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as exc:
        return f"Model configuration failed: {exc}."
    return json.dumps({
        "model_id": model_id,
        "allowed_devices": result.get("allowed_devices"),
        "context_tokens": result.get("context_tokens"),
        "max_output_tokens": result.get("max_output_tokens"),
        "gpu_memory_utilization": result.get("gpu_memory_utilization"),
        "max_num_seqs": result.get("max_num_seqs"),
        "source_manifest": result.get("source_manifest"),
    }, sort_keys=True)
