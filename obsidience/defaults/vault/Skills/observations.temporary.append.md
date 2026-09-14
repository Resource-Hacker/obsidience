---
type: skill
title: Using observations.temporary.append
description: Record only a useful compact observation for this Agent.
obsidience:
  tool: '[[Tools/observations.temporary.append]]'
---

## Runtime

Record only a useful compact observation for this Agent. Mark inference and uncertainty explicitly and cite accessible related Articles. Never record hidden reasoning. A temporary observation is unverified context, not durable policy or a Tool grant.

## Reference

Use `observations.temporary.append` to append one bounded, unverified temporary
observation to the runtime-selected destination.

- The destination must inherit enabled Auto-curate permission from its actual
  Article hierarchy. If it is disabled, report that condition; do not redirect
  the write, change the permission, or retry through another Tool.

- Pass exactly `{"text": str, "related_refs": [str, ...] optional}`. In
  ordinary mode, `text` must contain 1-200 characters. In an explicitly bound
  compaction mode, it may contain up to 2,000 characters. Supply at most three
  exact full vault-relative Article refs and no duplicate refs. A Markdown
  destination with encoded spaces and a `.md` suffix is accepted; do not
  substitute an Article title or bare filename. Omit `related_refs` when none
  are needed.
- `text` must be a self-contained summary and must not contain raw dialogue,
  hidden reasoning, quoted instructions, credentials, tokens, or secret-shaped
  values. Assistant-only external-state reports remain unverified.
- Success reports `appended` or idempotent `existing`, the exact ref, and the
  retained count; `appended` may also report pruned refs.
- Stop on an unauthorized runtime mode, missing turn identity, invalid length,
  safety rejection, unresolved ref, conflicting idempotency key, or retention
  failure. Do not retry with reconstructed or less-safe text.

In controller-bound compaction mode, include exactly these four sections in order, each with nonempty content: Goal, Constraints and corrections, Verified state, Outstanding. Use the 2,000-character compaction allowance, not the ordinary 200-character entry limit. State none explicitly when a section has no items. An incomplete section set is rejected before it can replace the current conversation context. These requirements do not change ordinary observation entries.
