"""Fast hybrid retrieval shared by every Obsidience activation.

FTS and dense-vector ranks fuse deterministically, then a small allowance of
direct graph neighbors enriches the strongest accepted Knowledge matches.
There is no generative expansion, cross-encoder, or elapsed-time deadline.
Edges dispatch; retrieval only supplies context and may nominate a Task.
"""

from __future__ import annotations

import time

from ..config import CONFIG
from .index import INDEX
from .vault import load_note, resolver

RRF_ORIGINAL_WEIGHT = 2.0
FAST_CONTEXT_LIMIT = 5
FAST_CONTEXT_DIRECT_FLOOR = 3
FAST_CONTEXT_GRAPH_LIMIT = 2
PREWARM_QUERY = "Obsidience activation knowledge"

# ---------- fusion ----------

def rrf_fuse(lanes: list[tuple[float, list[tuple[str, float]]]], k: int | None = None) -> list[str]:
    """Weighted reciprocal-rank fusion: lanes are (weight, results)."""
    k = k or CONFIG.rrf_k
    scores: dict[str, float] = {}
    for weight, lane in lanes:
        for rank, (ref, _s) in enumerate(lane):
            scores[ref] = scores.get(ref, 0.0) + weight / (k + rank + 1)
    return [r for r, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def _lanes_for(query: str, weight: float, k: int) -> list[tuple[float, list[tuple[str, float]]]]:
    return [(weight, INDEX.fts(query, k)), (weight, INDEX.vector(query, k))]


def search(query: str, k: int | None = None) -> list[dict]:
    """Fast interactive search: lexical+dense weighted RRF, with no model pass."""
    k = k or CONFIG.search_k
    ranked = rrf_fuse(_lanes_for(query, RRF_ORIGINAL_WEIGHT, k))[:k]
    out = []
    for ref in ranked[:12]:
        note = load_note(ref + ".md")
        if note:
            out.append({"ref": ref, "title": note.title, "kind": note.kind,
                        "snippet": note.body[:280]})
    return out


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # cheap estimate


def fast_context_with_refs(
    query: str,
    exclude: set[str],
    budget: int = 1_200,
    limit: int = FAST_CONTEXT_LIMIT,
    preferred: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Deterministic no-timeout context for every Task activation.

    This is the proven low-latency HEREBRUM/JARVIS shape: the original query
    enters lexical and dense lanes, their ranks fuse deterministically, and a
    maximum of two graph neighbors may enrich a floor of three direct hits.
    It deliberately has no LLM expansion, cross-encoder, or elapsed-time cap.
    """
    if not query.strip() or limit < 1:
        return "", []
    k = max(CONFIG.search_k, limit)
    ranked: list[str] = []
    for ref in rrf_fuse(_lanes_for(query, RRF_ORIGINAL_WEIGHT, k)):
        note = load_note(ref + ".md")
        if (
            ref not in exclude
            and note
            and note.kind == "knowledge"
            and note.meta.get("temporary") is not True
        ):
            ranked.append(ref)

    # A checked-out Source tree is a bounded retrieval preference, never an
    # authority edge or an unconditional prompt attachment.  Preserve the
    # fused search order inside both partitions.
    preferred_refs = preferred or set()
    if preferred_refs:
        ranked = [ref for ref in ranked if ref in preferred_refs] + [
            ref for ref in ranked if ref not in preferred_refs
        ]

    direct_floor = min(FAST_CONTEXT_DIRECT_FLOOR, limit, len(ranked))
    direct_seeds = ranked[:direct_floor]
    graph_budget = min(FAST_CONTEXT_GRAPH_LIMIT, max(0, limit - direct_floor))
    res = resolver()
    graph_refs: list[str] = []
    candidates_by_seed: list[list[str]] = []
    for ref in direct_seeds:
        note = load_note(ref + ".md")
        candidates: list[str] = []
        for target in note.links if note else []:
            hit = res.resolve(target)
            if (
                hit
                and hit.kind == "knowledge"
                and hit.meta.get("temporary") is not True
                and hit.ref not in exclude
                and hit.ref not in ranked
                and hit.ref not in candidates
            ):
                candidates.append(hit.ref)
        candidates_by_seed.append(candidates)

    # Round-robin across seeds so one high-degree article cannot consume the
    # complete graph allowance.
    while len(graph_refs) < graph_budget and any(candidates_by_seed):
        progressed = False
        for candidates in candidates_by_seed:
            while candidates and candidates[0] in graph_refs:
                candidates.pop(0)
            if candidates and len(graph_refs) < graph_budget:
                graph_refs.append(candidates.pop(0))
                progressed = True
        if not progressed:
            break

    direct_limit = max(0, limit - len(graph_refs))
    ordered = [*ranked[:direct_limit], *graph_refs]
    parts: list[str] = []
    included: list[str] = []
    used = 0
    for ref in ordered:
        note = load_note(ref + ".md")
        if not note:
            continue
        origin = "graph neighbor" if ref in graph_refs else "direct match"
        chunk = f"### [[{ref}]] — {note.title} ({origin})\n{note.body[:1200].strip()}\n"
        cost = _tokens(chunk)
        if used + cost > budget:
            if used > 0:
                break
            chunk = chunk[: budget * 4]
            cost = budget
        parts.append(chunk)
        included.append(ref)
        used += cost
    if not parts:
        return "", []
    return "\n".join(parts), included


def prewarm_fast_context() -> float:
    """Initialize the exact lexical+dense path before the first activation."""
    started = time.perf_counter()
    fast_context_with_refs(PREWARM_QUERY, set(), budget=128, limit=1)
    return (time.perf_counter() - started) * 1_000
