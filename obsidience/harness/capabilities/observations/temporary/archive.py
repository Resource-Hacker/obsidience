"""Adapter for ``observations.temporary.archive``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.conversation.observations import archive_temporary_observations

    context = context or {}
    runtime = {
        **(context.get("params") or {}),
        "origin_task_ref": str(context.get("task", "")),
        "event": str(context.get("event", "")),
    }
    try:
        result = archive_temporary_observations(args or {}, runtime)
    except ValueError as exc:
        return f"Temporary archive rejected: {exc}."
    context["_observation_archive"] = dict(result["source"])
    return json.dumps(result, sort_keys=True)
