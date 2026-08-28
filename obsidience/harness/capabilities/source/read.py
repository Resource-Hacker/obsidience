"""Adapter for ``source.read``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.source import SourceError, get_source

    try:
        result = get_source(str((args or {}).get("source", "")))
    except SourceError as exc:
        return f"Source unavailable: {exc}"
    return (
        f"{result['citation']} · {result['source_type']} · {result['captured_at']}\n"
        f"Reference: {result['source_ref'] or '(none)'}\n"
        f"SHA-256: {result['content_sha256']}\n\n"
        f"{result['content'][:12_000]}"
    )
