---
binding: capability:observations.temporary.append
kind: tool
source: obsidience/harness/capabilities/observations/temporary/append.py
title: observations.temporary.append
---

Append one transient, unverified observation to the current auto-curated
Temporary Observations node.

Arguments: `{ "text": "bounded summary", "related_refs": ["up to three exact article refs"] }`.

Ordinary working-memory entries are limited to 200 characters. The
`observations/immediate/compact` Task may write one cumulative context summary
of at most 2,000 characters. The binding is idempotent per source boundary and
enforces 10 entries, 20,000 characters total, and a 24-hour TTL. It cannot
write durable knowledge.
