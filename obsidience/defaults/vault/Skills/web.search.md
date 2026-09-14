---
type: skill
title: Using web.search
description: Use a focused query for the identified gap.
obsidience:
  tool: '[[Tools/web.search]]'
  requires:
  - '[[Skills/web.fetch]]'
---

## Runtime

Use a focused query for the identified gap. Prefer primary sources and retain the exact result URL before fetching. Search snippets establish leads, not the full source's conclusions.

## Reference

Use `web.search` to discover a bounded set of direct public source candidates.

- Pass exactly `{"query": str, "limit": int optional}`. `query` must contain
  1-300 characters. `limit` is clamped to 1-8 and defaults to five.
- Success returns the normalized query and numbered results containing a title,
  public URL, and bounded description. Each result is a discovery lead, not
  source evidence.
- Prefer specific queries whose returned publishers and dates can be inspected;
  never treat a snippet as complete or authoritative content.
- Stop on `Web search failed`, invalid arguments, timeout, malformed provider
  output, or no public results. Retry only with a materially different bounded
  query; never invent a URL or result.
