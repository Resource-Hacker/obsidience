---
type: tool
title: web.search
description: Acquire bounded current-source leads using query and optional limit.
obsidience:
  binding: capability:web.search
  source: obsidience/harness/capabilities/web/search.py
---

## Runtime

Acquire bounded current-source leads using query and optional limit. Results are leads, not complete evidence; open the exact source needed for the identified question. Do not broaden a bound Feed distillation into research.

## Reference

Search the public web for direct source candidates.

Arguments:

- `query`: a focused search query of at most 300 characters.
- `limit`: one to eight results; defaults to five.

The result contains titles, public URLs, and short discovery snippets. Search
results are leads rather than evidence; use `web.fetch` on a direct result
before relying on it.
