"""Adapter for ``model.configure``."""

from __future__ import annotations

import json

from obsidience.harness.models import runtime as model_runtime


async def execute(args: dict, context: dict) -> str:
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
        result = await model_runtime.update_model(model_id, payload)
    except (TypeError, ValueError, RuntimeError) as exc:
        return f"Model configuration failed: {exc}."
    if result.get("cancellation_requested") is True:
        context["_capability_cancelled_after_commit"] = True
    projected = {
        "model_id": model_id,
        "allowed_devices": result.get("allowed_devices"),
        "context_tokens": result.get("context_tokens"),
        "max_output_tokens": result.get("max_output_tokens"),
        "gpu_memory_utilization": result.get("gpu_memory_utilization"),
        "max_num_seqs": result.get("max_num_seqs"),
        "source_manifest": result.get("source_manifest"),
    }
    for key in (
        "configuration_applied", "configuration_source", "runtime_reconciled",
        "reconciliation_warning",
    ):
        if key in result:
            projected[key] = result[key]
    return json.dumps(projected, sort_keys=True)
