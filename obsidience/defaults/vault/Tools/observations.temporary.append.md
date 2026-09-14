---
type: tool
title: observations.temporary.append
description: Write an unverified observation under the executing Agent's own Temporary
  Observations using text and up to three accessible related_refs.
obsidience:
  binding: capability:observations.temporary.append
  source: obsidience/harness/capabilities/observations/temporary/append.py
---

## Runtime

Write an unverified observation under the executing Agent's own Temporary Observations using text and up to three accessible related_refs. Ordinary notes allow 200 characters; the exact Compact Task permits 2,000 in its required cumulative format. The controller supplies identity and target. Another Agent's Observation path cannot be selected.

## Reference

Append one transient, unverified observation to the Temporary Observations
node bound by the active Task.

The destination must have effective owner Auto-curate permission. An explicit
false on that branch or a nearer ancestor blocks the write; the Task cannot
grant itself permission. Turning the checkbox on does not create a new Task.

Arguments: `{ "text": "bounded summary", "related_refs": ["up to three exact article refs"] }`.

Ordinary entries are limited to 200 characters. Only the exact Compact Task
and Executive target may write a cumulative context summary of at most 2,000
characters. Related refs are full vault-relative Article paths; encoded spaces,
an optional leading `/`, and an optional `.md` suffix normalize to the same
identity. Titles and basenames are not substitutes for an exact path. Every
related ref must resolve before any write. Repeating the same completed-turn
identity with the same text returns `existing`; different text for that turn
is rejected.

The live cache normally retains at most 10 entries, 20,000 characters, and 24
hours. Entries awaiting a bound promotion remain until archived. This Tool
cannot create durable Knowledge.

In controller-bound compaction mode, include exactly these four sections in order, each with nonempty content: Goal, Constraints and corrections, Verified state, Outstanding. Use the 2,000-character compaction allowance, not the ordinary 200-character entry limit. State none explicitly when a section has no items. An incomplete section set is rejected before it can replace the current conversation context. These requirements do not change ordinary observation entries.
