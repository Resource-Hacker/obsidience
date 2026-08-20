"""Retrieval — the qmd-derived pipeline carried over from the ADR-0001 work:

    LLM query expansion (typed lex/vec sub-queries, bounded cache)
      -> FTS + vector lanes -> weighted RRF (k=60, 2x original query)
      -> ONNX cross-encoder rerank (offline, same model the old stack used)
      -> one-hop typed-link expansion -> token-budgeted packing

Law: edges dispatch, vectors inform. This module only assembles *context*.
`search()` is the fast interactive path (no LLM expansion); `briefing()` is
the full activation pipeline.
"""

from __future__ import annotations

import json
import re
import threading

import httpx

from .config import CONFIG
from .indexer import INDEX
from .vault import load_note, resolver

RRF_ORIGINAL_WEIGHT = 2.0

# ---------- LLM query expansion (bounded cache) ----------

_expansion_cache: dict[str, dict] = {}
_EXPANSION_CACHE_MAX = 128

_EXPAND_PROMPT = """\
Expand this retrieval query for a personal wiki into search variants.
Reply with ONLY a JSON object: {"lex": ["<2-4 keyword queries>"], "vec": ["<1-2 natural-language reformulations>"]}
Query: %s"""


def expand_query(query: str) -> dict:
    key = query.strip().lower()[:200]
    if key in _expansion_cache:
        return _expansion_cache[key]
    out = {"lex": [], "vec": []}
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(f"{CONFIG.llm_base_url}/chat/completions", json={
                "model": CONFIG.llm_model, "temperature": 0.2, "max_tokens": 200,
                "messages": [{"role": "user", "content": _EXPAND_PROMPT % query[:300]}],
            })
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                out["lex"] = [str(q) for q in parsed.get("lex", [])][:4]
                out["vec"] = [str(q) for q in parsed.get("vec", [])][:2]
    except Exception:  # noqa: BLE001 — expansion is best-effort
        pass
    if len(_expansion_cache) >= _EXPANSION_CACHE_MAX:
        _expansion_cache.pop(next(iter(_expansion_cache)))
    _expansion_cache[key] = out
    return out


# ---------- cross-encoder reranker (offline, lazy) ----------

_reranker = None
_rerank_lock = threading.Lock()
_rerank_failed = False


def _get_reranker():
    global _reranker, _rerank_failed
    if _rerank_failed:
        return None
    with _rerank_lock:
        if _reranker is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                _reranker = TextCrossEncoder(
                    model_name="Xenova/ms-marco-MiniLM-L-6-v2",
                    cache_dir=CONFIG.embed_cache_dir,
                )
            except Exception:  # noqa: BLE001 — degrade to fusion order
                _rerank_failed = True
                return None
    return _reranker


def rerank(query: str, refs: list[str]) -> list[str]:
    model = _get_reranker()
    if not model or len(refs) < 3:
        return refs
    docs, kept = [], []
    for ref in refs:
        note = load_note(ref + ".md")
        if note:
            docs.append(f"{note.title}\n{note.body[:900]}")
            kept.append(ref)
    if not docs:
        return refs
    scores = list(model.rerank(query, docs))
    order = sorted(range(len(kept)), key=lambda i: -scores[i])
    return [kept[i] for i in order]


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
    """Interactive path: lanes + weighted RRF + rerank (no LLM expansion)."""
    k = k or CONFIG.search_k
    fused = rrf_fuse(_lanes_for(query, RRF_ORIGINAL_WEIGHT, k))[:k]
    ranked = rerank(query, fused)
    out = []
    for ref in ranked[:12]:
        note = load_note(ref + ".md")
        if note:
            out.append({"ref": ref, "title": note.title, "kind": note.kind,
                        "snippet": note.body[:280]})
    return out


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # cheap estimate


def briefing(queries: list[str], exclude: set[str], budget: int | None = None) -> str:
    """Full activation pipeline, token-budget packed."""
    budget = budget or CONFIG.briefing_token_budget
    k = CONFIG.search_k
    lanes: list[tuple[float, list[tuple[str, float]]]] = []
    for q in queries[:3]:
        lanes.extend(_lanes_for(q, RRF_ORIGINAL_WEIGHT, k))
    expansion = expand_query(" ".join(queries[:2]))
    for q in expansion["lex"]:
        lanes.append((1.0, INDEX.fts(q, k)))
    for q in expansion["vec"]:
        lanes.append((1.0, INDEX.vector(q, k)))

    fused = [r for r in rrf_fuse(lanes) if r not in exclude and not r.startswith("Receipts/")]
    ranked = rerank(" ".join(queries[:2]), fused[:k])

    # one-hop typed-link expansion off the top hits
    res = resolver()
    hops: list[str] = []
    for ref in ranked[:5]:
        note = load_note(ref + ".md")
        for target in (note.links if note else [])[:4]:
            hit = res.resolve(target)
            if hit and hit.ref not in exclude and hit.ref not in ranked and not hit.ref.startswith("Receipts/"):
                hops.append(hit.ref)

    parts, used, seen = [], 0, set(exclude)
    for ref in [*ranked, *hops]:
        if ref in seen:
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
