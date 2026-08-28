"""Adapter for ``source.handoff``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    """Write one cited Darwin finding to the physical Source Inbox."""
    from obsidience.harness.knowledge.source import SourceError, handoff_source

    if str(context.get("agent", "")) != "Darwin" or not str(
        context.get("task", "")
    ).startswith("Tasks/research/"):
        return "Source handoff rejected: only Darwin Research Tasks may write the Inbox."
    try:
        result = handoff_source(
            title=str((args or {}).get("title", "")),
            content=str((args or {}).get("content", "")),
        )
    except SourceError as exc:
        return f"Source handoff rejected: {exc}"
    event = result.get("source_event")
    count = len(event.get("occurrences") or []) if isinstance(event, dict) else 0
    return (
        f"Research {'dropped' if result['created'] else 'already present'} at "
        f"obsidience/evidence/{result['path']} as {result['citation']} "
        f"({result['content_sha256']}). "
        f"source.inbox activated {count} Ingest Task{'s' if count != 1 else ''}."
    )
