---
title: vault.search
kind: tool
binding: builtin:vault.search
---
Hybrid search (BM25 + vector, RRF-fused) over the vault. args: `{"query": str}`.
Returns up to 10 refs with kind and snippet. Results are context, not truth —
read the note before acting on it.
