"""Hybrid retrieval + the activation briefing.

Law: edges dispatch, vectors inform. This module only assembles *context*.
Pipeline: deterministic queries from the spine -> FTS + vector lanes -> RRF
fusion -> token-budgeted packing. (Hooks left for LLM query expansion and
reranking — v0 keeps it deterministic and fast.)
"""

from __future__ import annotations

from .config import CONFIG
from .indexer import INDEX
from .vault import load_note


def rrf_fuse(lanes: list[list[tuple[str, float]]], k: int | None = None) -> list[str]:
    k = k or CONFIG.rrf_k
    scores: dict[str, float] = {}
    for lane in lanes:
        for rank, (ref, _s) in enumerate(lane):
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (k + rank + 1)
    return [r for r, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def search(query: str, k: int | None = None) -> list[dict]:
    k = k or CONFIG.search_k
    fused = rrf_fuse([INDEX.fts(query, k), INDEX.vector(query, k)])[:k]
    out = []
    for ref in fused:
        note = load_note(ref + ".md")
        if note:
            out.append({"ref": ref, "title": note.title, "kind": note.kind,
                        "snippet": note.body[:280]})
    return out


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # cheap estimate


def briefing(queries: list[str], exclude: set[str], budget: int | None = None) -> str:
    """Assemble the activation briefing: fused results packed under a token budget."""
    budget = budget or CONFIG.briefing_token_budget
    lanes = []
    for q in queries[:4]:
        lanes.append(INDEX.fts(q, CONFIG.search_k))
        lanes.append(INDEX.vector(q, CONFIG.search_k))
    parts, used, seen = [], 0, set(exclude)
    for ref in rrf_fuse(lanes):
        if ref in seen or ref.startswith("Receipts/"):
            continue
        seen.add(ref)
        note = load_note(ref + ".md")
        if not note:
            continue
        chunk = f"### [[{ref}]] — {note.title}\n{note.body[:1200].strip()}\n"
        cost = _tokens(chunk)
        if used + cost > budget:
            if used > 0:
                break
            chunk = chunk[: budget * 4]
            cost = budget
        parts.append(chunk)
        used += cost
    if not parts:
        return ""
    return "## Relevant vault context (background only — follow the runbook)\n\n" + "\n".join(parts)
