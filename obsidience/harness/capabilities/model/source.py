"""Adapter for ``model.source``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.models.runtime import sync_model_source

    try:
        result = sync_model_source(str((args or {}).get("model_id", "")))
    except ValueError as exc:
        return f"Model Source registration rejected: {exc}."
    return (
        f"Model artifact registered at {result['source_path']} "
        f"({result['fingerprint']})."
    )
