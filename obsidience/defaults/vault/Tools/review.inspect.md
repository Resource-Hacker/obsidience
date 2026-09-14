---
type: tool
title: review.inspect
description: Read bounded review evidence for an exact task or proposal.
obsidience:
  binding: capability:review.inspect
  source: obsidience/harness/capabilities/review/inspect.py
---

## Runtime

Read bounded review evidence for an exact task or proposal. Missing, stale or clipped records are not approval. Inspect existing dispositions before proposing another change. Review is not permission to replay effects.

## Reference

Read pending review evidence without accepting, rejecting or modifying it.
Arguments: `{"task":"optional exact Task ref","proposal":"optional exact filename"}`.

An empty object lists up to eight pending proposal summaries. `task` narrows
to one accepted Task; `proposal` selects one exact returned filename and includes
a bounded body preview. Results include provenance, exact target, review class,
changed links, revision warnings and approval blockers. Truncation is explicit.
An empty result means no matching pending proposal, not that any change was
approved. This Tool does not expose an approval command or historical verdict.
