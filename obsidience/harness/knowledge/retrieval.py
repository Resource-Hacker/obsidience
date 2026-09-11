"""Fast hybrid retrieval shared by every Obsidience activation.

FTS and dense-vector ranks fuse deterministically, then a small allowance of
direct graph neighbors enriches the strongest accepted Knowledge matches.
There is no generative expansion, cross-encoder, or elapsed-time deadline.
Edges dispatch; retrieval only supplies context and may nominate a Task.
"""

from __future__ import annotations

import time
import re
from datetime import datetime, timezone

from ..config import CONFIG
from .format import ARTICLE_TYPES, lifecycle_metadata
from .index import INDEX
from .vault import SOURCE_DIRS, SYSTEM_DIRS, Note, Resolver, iter_notes, load_note

RRF_ORIGINAL_WEIGHT = 2.0
FAST_CONTEXT_LIMIT = 5
FAST_CONTEXT_DIRECT_FLOOR = 3
FAST_CONTEXT_GRAPH_LIMIT = 2
FAST_CONTEXT_ACCOUNTING_LIMIT = 32
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


def _lanes_for(
    query: str,
    weight: float,
    k: int,
    kind: str | None = None,
    *,
    eligible_refs: set[str] | None = None,
) -> list[tuple[float, list[tuple[str, float]]]]:
    filters = {"eligible_refs": eligible_refs} if eligible_refs is not None else {}
    return [
        (weight, INDEX.fts(query, k, kind, **filters)),
        (weight, INDEX.vector(query, k, kind, **filters)),
    ]


def normalize_search_scope(value: object) -> dict:
    """Validate optional retrieval restrictions; these grant no Article authority."""
    if not isinstance(value, dict) or set(value) - {"kind", "current_only", "exclude_subtrees"}:
        raise ValueError("scope accepts only kind, current_only and exclude_subtrees")
    kind = value.get("kind")
    if "kind" in value and (not isinstance(kind, str) or kind not in ARTICLE_TYPES):
        raise ValueError("scope.kind must be an existing Article kind")
    current = value.get("current_only", False)
    if type(current) is not bool:
        raise ValueError("scope.current_only must be a boolean")
    roots = value.get("exclude_subtrees", [])
    if not isinstance(roots, list) or len(roots) > 10:
        raise ValueError("scope.exclude_subtrees requires at most 10 canonical roots")
    for root in roots:
        if (not isinstance(root, str) or not 1 <= len(root) <= 300 or root.endswith(".md")
                or any(char in root for char in "\\[]#|") or any(ord(char) < 32 or ord(char) == 127 for char in root)
                or any(part in {"", ".", ".."} or part != part.strip() for part in root.split("/"))):
            raise ValueError("scope.exclude_subtrees requires canonical vault-relative roots without .md")
    if len(set(roots)) != len(roots):
        raise ValueError("scope.exclude_subtrees cannot repeat a root")
    return {**({"kind": kind} if kind is not None else {}),
            "current_only": current, "exclude_subtrees": sorted(roots)}


def _matches_search_scope(note: Note, scope: dict, now: datetime) -> bool:
    if scope.get("kind") is not None and note.kind != scope["kind"]:
        return False
    if any(note.ref == root or note.ref.startswith(root + "/") for root in scope["exclude_subtrees"]):
        return False
    if scope["current_only"] and (
        note.runtime_observation or note.meta.get("retrieval", True) is False
        or lifecycle_metadata(note.meta, now)["freshness"] != "current"
    ):
        return False
    return True


def search(query: str, k: int | None = None, *, scope: dict | None = None,
           snapshot: list[Note] | None = None, allowed_refs: set[str] | None = None) -> list[dict]:
    """Fast interactive search: lexical+dense weighted RRF, with no model pass."""
    k = k or CONFIG.search_k
    if scope is None and allowed_refs is None:
        ranked = rrf_fuse(_lanes_for(query, RRF_ORIGINAL_WEIGHT, k))[:k]
        accepted = None
    else:
        scope = normalize_search_scope(scope or {})
        now = datetime.now(timezone.utc)
        # A batch reuses one fresh accepted-Article snapshot, never a persistent
        # policy cache. Time-based freshness is still evaluated for each query.
        accepted = {note.ref: note for note in (snapshot if snapshot is not None else iter_notes())
                    if _matches_search_scope(note, scope, now)
                    and (allowed_refs is None or note.ref in allowed_refs)}
        if not accepted:
            return []
        ranked = rrf_fuse(_lanes_for(query, RRF_ORIGINAL_WEIGHT, k, scope.get("kind"),
                                     eligible_refs=set(accepted)))[:k]
    out = []
    for ref in ranked[:12]:
        note = accepted.get(ref) if accepted is not None else load_note(ref + ".md")
        if note:
            out.append({"ref": ref, "title": note.title, "kind": note.kind,
                        "snippet": note.body[slice(*passage_range(note.body, query, 280))]})
    return out



def passage_range(body: str, query: str, maximum: int = 1200) -> tuple[int, int]:
    """Choose a contiguous evidence passage without rewriting its contents.

    Paragraph windows retain negations/context and exact character offsets.
    Long single paragraphs use overlapping word-boundary windows. This is a
    deterministic selection aid, not a claim that omitted text is irrelevant.
    """
    if not body or maximum < 1:
        return 0, 0
    if len(body) <= maximum:
        return len(body) - len(body.lstrip()), len(body.rstrip())
    terms = {word.casefold() for word in re.findall(r"[^\W_]+", query) if len(word) > 2}
    terms -= {"the", "this", "that", "with", "from", "what", "which", "please", "about", "would", "could"}
    spans = [(match.start(), match.end()) for match in re.finditer(r"\S(?:[\s\S]*?)(?=\n\s*\n|\Z)", body)]
    starts = {0, *(start for start, _ in spans)}
    for start, end in spans:
        if end-start > maximum:
            for offset in range(start, end, max(1, maximum // 2)):
                boundary = body.find(" ", offset, min(end, offset+80))
                starts.add(boundary+1 if boundary >= 0 and offset != start else offset)
    best = (float("-inf"), 0, min(maximum, len(body)))
    for start in sorted(starts):
        end = min(start+maximum, len(body))
        complete = [stop for a, stop in spans if a >= start and stop <= end]
        if complete:
            end = max(complete)
        elif end < len(body):
            boundary = body.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        text = body[start:end]
        words = [word.casefold() for word in re.findall(r"[^\W_]+", text)]
        hits = terms.intersection(words)
        score = len(hits) * 100 + sum(min(words.count(term), 3) for term in hits)
        # Prefer the first complete occurrence at equal relevance, not length.
        candidate = (score, -start)
        if candidate > (best[0], -best[1]):
            best = (score, start, end)
    _, start, end = best
    while start < end and body[start].isspace(): start += 1
    while end > start and body[end-1].isspace(): end -= 1
    return start, end


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # cheap estimate


def _eligible_knowledge(note: Note | None, now: datetime) -> bool:
    """Admit current accepted Knowledge, without changing historical access."""

    if not (
        note
        and note.kind == "knowledge"
        and note.meta.get("retrieval", True) is not False
        and note.meta.get("temporary") is not True
    ):
        return False
    lifecycle = lifecycle_metadata(note.meta, now)
    return lifecycle["freshness"] == "current" and lifecycle.get("status") != "draft"


def fast_context_with_refs(
    query: str,
    exclude: set[str],
    budget: int = 1_200,
    limit: int = FAST_CONTEXT_LIMIT,
    preferred: set[str] | None = None,
    *,
    accepted_resolver: Resolver | None = None,
    diagnostics: dict | None = None,
    allowed_refs: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Deterministic no-timeout context for every Task activation.

    The original query enters lexical and dense lanes, their ranks fuse
    deterministically, and a
    maximum of two graph neighbors may enrich a floor of three direct hits.
    It deliberately has no LLM expansion, cross-encoder, or elapsed-time cap.
    """
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update({
            "version": 1, "scope": "eligible_search_hits_and_seed_neighbors",
            "search_limit": max(CONFIG.search_k, limit), "article_limit": limit,
            "considered_count": 0, "included_count": 0, "omitted_count": 0,
            "entries_omitted": 0, "estimated_budget_tokens": budget,
            "estimated_used_tokens": 0, "estimate_method": "chunk_chars_div_4",
            "status": "empty_query" if not query.strip() else "disabled" if limit < 1 else "no_matches",
            "entries": [],
        })
    if not query.strip() or limit < 1:
        return "", []
    # The compiler may provide its fresh activation snapshot. Never retain it
    # between activations; freshness below is evaluated at this call's time.
    accepted_notes = (
        list(accepted_resolver.by_ref.values())
        if accepted_resolver is not None else iter_notes()
    )
    accepted_notes = [note for note in accepted_notes
                      if note.path.split("/")[0] not in (*SYSTEM_DIRS, *SOURCE_DIRS)
                      and not any(part.startswith(".") for part in note.path.split("/"))
                      and (allowed_refs is None or note.ref in allowed_refs)]
    now = datetime.now(timezone.utc)
    accepted_by_ref = {note.ref: note for note in accepted_notes}
    context_resolver = Resolver(accepted_notes)
    k = max(CONFIG.search_k, limit)
    ranked: list[str] = []
    for ref in rrf_fuse(
        _lanes_for(query, RRF_ORIGINAL_WEIGHT, k, "knowledge",
                   eligible_refs={ref for ref, note in accepted_by_ref.items()
                                  if ref not in exclude and _eligible_knowledge(note, now)})
    ):
        note = accepted_by_ref.get(ref)
        if ref not in exclude and _eligible_knowledge(note, now):
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
    graph_refs: list[str] = []
    graph_origins: dict[str, str] = {}
    candidates_by_seed: list[list[str]] = []
    for ref in direct_seeds:
        note = accepted_by_ref.get(ref)
        candidates: list[str] = []
        for target in note.links if note else []:
            hit = context_resolver.resolve(target)
            if (
                hit
                and _eligible_knowledge(hit, now)
                and hit.ref not in exclude
                and hit.ref not in ranked
                and hit.ref not in candidates
            ):
                candidates.append(hit.ref)
                if diagnostics is not None:
                    graph_origins.setdefault(hit.ref, ref)
        candidates_by_seed.append(candidates)

    # Round-robin across seeds so one high-degree article cannot consume the
    # complete graph allowance.
    while len(graph_refs) < graph_budget and any(candidates_by_seed):
        progressed = False
        for seed_ref, candidates in zip(direct_seeds, candidates_by_seed):
            while candidates and candidates[0] in graph_refs:
                candidates.pop(0)
            if candidates and len(graph_refs) < graph_budget:
                ref = candidates.pop(0)
                graph_refs.append(ref)
                if diagnostics is not None:
                    graph_origins[ref] = seed_ref
                progressed = True
        if not progressed:
            break

    direct_limit = max(0, limit - len(graph_refs))
    ordered = [*ranked[:direct_limit], *graph_refs]
    parts: list[str] = []
    included: list[str] = []
    packed: dict[str, tuple[str, int]] = {}
    budget_stop_ref: str | None = None
    passages = {ref: passage_range(accepted_by_ref[ref].body, query)
                for ref in dict.fromkeys([*ordered, *ranked, *graph_origins])}
    used = 0
    for ref in ordered:
        note = accepted_by_ref.get(ref)
        if not note:
            continue
        origin = "graph neighbor" if ref in graph_refs else "direct match"
        chunk = f"### [[{ref}]] — {note.title} ({origin})\n{note.body[slice(*passages[ref])]}\n"
        cost = _tokens(chunk)
        if used + cost > budget:
            if used > 0:
                budget_stop_ref = ref
                break
            chunk = chunk[: budget * 4]
            cost = budget
        parts.append(chunk)
        included.append(ref)
        used += cost
        if diagnostics is not None:
            packed[ref] = (chunk, cost)
    if diagnostics is not None:
        _record_fast_context(diagnostics, accepted_by_ref, ranked, graph_origins,
                             ordered, packed, preferred_refs, budget_stop_ref, used, passages)
    if not parts:
        return "", []
    return "\n".join(parts), included


def _record_fast_context(diagnostics: dict, notes: dict[str, Note], ranked: list[str],
                         graph_origins: dict[str, str], ordered: list[str],
                         packed: dict[str, tuple[str, int]], preferred: set[str],
                         budget_stop_ref: str | None, used: int,
                         passages: dict[str, tuple[int, int]] | None = None) -> None:
    """Explain this bounded nomination pass without changing prompt selection.

    Counts cover eligible lane hits and neighbors examined from the direct seeds,
    not the complete Vault. Body offsets are Unicode character offsets, end
    exclusive, into the accepted snapshot. Full means all non-whitespace body
    text was supplied; omitted_chars also counts trimmed boundary whitespace.
    Estimated usage retains the packer's existing per-chunk floor and first-item
    budget charge. It excludes joining separators and is not provider tokenization.
    """
    candidates = dict.fromkeys([*ordered, *ranked, *graph_origins])
    diagnostics.update({
        "considered_count": len(candidates), "included_count": len(packed),
        "omitted_count": len(candidates) - len(packed),
        "entries_omitted": max(0, len(candidates) - FAST_CONTEXT_ACCOUNTING_LIMIT),
        "estimated_used_tokens": used, "status": "selected" if packed else "no_matches",
    })
    entries = diagnostics["entries"]
    for ref in list(candidates)[:FAST_CONTEXT_ACCOUNTING_LIMIT]:
        note = notes[ref]
        graph = ref in graph_origins
        header = f"### [[{ref}]] — {note.title} ({'graph neighbor' if graph else 'direct match'})\n"
        body_start, body_stop = (passages or {}).get(ref, passage_range(note.body, ""))
        excerpt = note.body[body_start:body_stop]
        selected, charged = packed.get(ref, ("", 0))
        body_length = min(len(excerpt), max(0, len(selected) - len(header)))
        if ref in packed:
            reason = "selected"
        elif ref == budget_stop_ref:
            reason = "token_budget"
        elif ref in ordered:
            reason = "after_budget_stop"
        else:
            reason = "graph_limit" if graph else "article_limit"
        entries.append({
            "ref": ref, "title": note.title, "origin": "graph" if graph else "direct",
            "seed_ref": graph_origins.get(ref), "preferred": ref in preferred,
            "decision": "included" if ref in packed else "omitted", "reason": reason,
            "content": ("none" if ref not in packed or body_length == 0 and note.body.strip()
                        else "full" if body_length == len(note.body.strip()) else "excerpt"),
            "body_chars": len(note.body),
            "body_start": body_start if body_length else None,
            "body_end": body_start + body_length if body_length else None,
            "omitted_chars": len(note.body) - body_length,
            "estimated_tokens": _tokens(header + excerpt + "\n"),
            "included_estimated_tokens": charged,
        })


def prewarm_fast_context() -> float:
    """Initialize the exact lexical+dense path before the first activation."""
    started = time.perf_counter()
    fast_context_with_refs(PREWARM_QUERY, set(), budget=128, limit=1)
    return (time.perf_counter() - started) * 1_000
