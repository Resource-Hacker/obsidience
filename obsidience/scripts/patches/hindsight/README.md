# Hindsight native patches

Apply the patches in numeric order to the pinned Hindsight environment. Exact
preimage and resulting module hashes are recorded in `artifacts.lock.json`.
The Hindsight service owns these modules; the Harness does not load them.

Patch 0007 follows 0002 for `engine/search/reranking.py`. It places qualified
memory text before date and provenance context in cross-encoder input. Stored
memories and their uncertainty, source labels and timestamps remain unchanged.

```sh
patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < obsidience/scripts/patches/hindsight/0007-rank-fact-before-provenance.patch
```

Reranker model selection remains native installation configuration. Validate
recall quality and API latency on the target CPU before selecting a larger model;
a change in ranking input order alone does not establish a latency or quality gain.

Patch 0008 supplies the detected calendar date or date range to the cross-encoder
query, so relative wording can be compared with dated facts. The original query
still drives retrieval. Patch 0009 follows 0004 and expands a named month without
a day to the whole month, retaining the resolved year and reference offset.
Neither patch changes memory text or makes temporal recall a hard date filter.

Patch 0010 separates Codex SSE framing from generated string deltas. It bounds
incoming wire data at 64 MiB and each line and cumulative generated deltas at
4,194,304 characters, while preserving the request wall deadline and semantic
parsers. Rejection diagnostics contain numeric counters, never generated text.
The Codex provider does not send the caller's completion-token limit; these are
local resource ceilings, not claims about the model's token budget.

Patch 0011 applies the semantic arm's similarity floor outside its ORDER BY/LIMIT.
The floor is monotone in the sort key, so the rows are unchanged, but the planner now
uses the per-bank partial HNSW index instead of an exact scan (store phase ~100 -> ~47 ms).
