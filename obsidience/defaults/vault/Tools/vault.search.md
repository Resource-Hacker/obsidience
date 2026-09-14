---
type: tool
title: vault.search
description: Search only the executing Agent's owned and checked-out graph.
obsidience:
  binding: capability:vault.search
  source: obsidience/harness/capabilities/vault/search.py
---

## Runtime

Search only the executing Agent's owned and checked-out graph. Pass query, or up to ten queries, and optional scope:{kind,current_only,exclude_subtrees}. Scope only narrows access. Results are evidence leads and exact snippets, not proof of the full Article or executable grants. Identify the missing fact before searching and stop repeated low-value searches.

## Reference

Hybrid BM25/vector search over the accepted graph. Supply exactly one of `query` or `queries`. Each query is 1-300 characters of nonempty focused descriptive text. `queries` contains 1-10 distinct queries. Invalid or oversized queries are rejected before search; they are not silently shortened.

A single query retains the existing text result with up to ten exact refs, Article kinds and bounded snippets. Each query in a batch returns up to five hits. Batch results are JSON `{"results":[{"query":"exact supplied query","ok":true,"result":"the same search-result text"}]}`. `No results.` is successful empty evidence; an unavailable query has `ok:false` and its actual error. Cancellation stops later queries.

Results are candidate context, not full Article evidence or truth. Read returned exact refs with `vault.read` before relying on their content or adding links. No Knowledge or Source is written.

Optional `scope` narrows the corpus before lexical and vector candidate limits. For current Knowledge outside a subtree, use `{"kind":"knowledge","current_only":true,"exclude_subtrees":["News & Research/Top Stories"]}`. One scope applies to every query in the batch. `kind` is an Article kind, `current_only` is a boolean, and `exclude_subtrees` contains at most ten canonical Article subtrees. Unknown keys and malformed values are rejected. Omit scope for the existing unrestricted historical search. The actual normalized scope is retained in the private search receipt.
