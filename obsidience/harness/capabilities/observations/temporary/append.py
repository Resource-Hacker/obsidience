"""Adapter for ``observations.temporary.append``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.conversation.observations import append_temporary_observation

    context = context or {}
    runtime = {
        **(context.get("params") or {}),
        "origin_task_ref": str(context.get("task", "")),
    }
    result = append_temporary_observation(args or {}, runtime)
    return (
        f"Temporary observation {result['status']} at [[{result['ref']}]] "
        f"({result['retained']} retained)."
    )
