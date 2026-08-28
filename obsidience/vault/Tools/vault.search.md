---
binding: capability:vault.search
kind: tool
source: obsidience/harness/capabilities/vault/search.py
title: vault.search
---

Hybrid BM25/vector search over the accepted graph. Argument:
`{"query": "focused descriptive text"}`.

The Tool returns up to ten refs with kind and snippet. Results are candidate
context, not truth; read the exact Article before relying on it.
