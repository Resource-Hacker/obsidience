"""Adapter for ``model.inspect``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.models.runtime import inspect_model

    try:
        result = inspect_model(str((args or {}).get("model_id", "")))
    except ValueError as exc:
        return f"Model inspection rejected: {exc}."
    return json.dumps(result, sort_keys=True)
