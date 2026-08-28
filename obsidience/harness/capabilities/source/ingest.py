"""Adapter for ``source.ingest``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.source import SourceError, ingest_source

    args = args or {}
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    activation_key = (
        str(params.get("activation_key"))
        if context.get("event") == "source.added"
        and str(params.get("activation_key", "")).startswith("source.added:")
        else None
    )
    try:
        result = ingest_source(
            source_type=str(args.get("source_type", "tool")),
            source_ref=str(args.get("source_ref", "")),
            media_type=str(args.get("media_type", "text/markdown")),
            captured_at=str(args["captured_at"]) if args.get("captured_at") else None,
            content=str(args.get("content", "")),
            activation_key=activation_key,
        )
    except SourceError as exc:
        return f"Source rejected: {exc}"
    message = (
        f"Source {'captured' if result['created'] else 'already captured'} as "
        f"{result['citation']} ({result['content_sha256']})."
    )
    event = result.get("source_event")
    if isinstance(event, dict):
        count = len(event.get("occurrences") or [])
        message += f" source.added activated {count} Research Task{'s' if count != 1 else ''}."
    return message
