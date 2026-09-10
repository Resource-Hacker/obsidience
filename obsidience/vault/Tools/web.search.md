---
type: tool
title: web.search
obsidience:
  binding: capability:web.search
  source: obsidience/harness/capabilities/web/search.py
---

Search the public web for direct source candidates.

Arguments:

- `query`: a focused search query of at most 300 characters.
- `limit`: one to eight results; defaults to five.

The result contains titles, public URLs, and short discovery snippets. Search
results are leads rather than evidence; use `web.fetch` on a direct result
before relying on it.
