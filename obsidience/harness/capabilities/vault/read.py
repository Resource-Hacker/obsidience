"""Adapter for ``vault.read``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.vault import iter_notes, load_note, resolver

    ref = str((args or {}).get("ref", "")).strip()
    res = resolver()
    note = res.resolve(ref) or load_note(ref if ref.endswith(".md") else ref + ".md")
    if not note:
        return f"Note not found: {ref}"
    inbound = []
    for candidate in iter_notes():
        if candidate.ref == note.ref:
            continue
        if any(
            (target := res.resolve(raw)) is not None and target.ref == note.ref
            for raw in candidate.links
        ):
            inbound.append(candidate.ref)
    graph_context = (
        "\n\n## Accepted inbound references\n"
        + (
            "\n".join(f"- [[{item}]]" for item in sorted(inbound)[:24])
            if inbound
            else "None."
        )
    )
    return (note.text()[:7200] + graph_context)[:8000]
