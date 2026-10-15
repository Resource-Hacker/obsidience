---
type: tool
title: web.search
description: Find public source leads using query and optional limit. Results are
  discovery snippets, not verified answers. Use web.fetch on a relevant result URL
  before relying on its claims.
obsidience:
  binding: capability:web.search
  source: obsidience/harness/capabilities/web/search.py
---

## Runtime

Acquire bounded current-source leads using query and optional limit. Results are leads, not complete evidence; open the exact source needed for the identified question.

## Reference

Search the public web for direct source candidates.

Arguments:

- `query`: a focused search query of at most 300 characters.
- `limit`: one to eight results; defaults to five.

The result contains titles, public URLs, and short discovery snippets. Search
results are leads rather than evidence; use `web.fetch` on a direct result
before relying on it.
