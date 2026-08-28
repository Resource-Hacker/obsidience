"""Adapter for ``vault.search``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.retrieval import search

    hits = search(str((args or {}).get("query", ""))[:300])
    if not hits:
        return "No results."
    return "\n".join(
        f"- [[{hit['ref']}]] ({hit['kind']}) — {hit['snippet'][:160]}"
        for hit in hits[:10]
    )
