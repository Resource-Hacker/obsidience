---
binding: capability:task.create
kind: tool
source: obsidience/harness/capabilities/task/create.py
title: task.create
---

Activate one exact accepted Task required by the active Runbook. Supply its
exact Task ref and a bounded `params` object. The target must explicitly accept
`task.create` events.

The target keeps its authored Agent, Runbook, model, reasoning effort,
acceptance conditions, and hierarchy. The activation packet and run ledger
record which Task activated it as causal provenance; that never creates a
parent, child, or subtask relation.

This Tool never authors a Task definition. Generate → Task creates or revises
reusable Task Articles through `vault.propose`.

The result state is `started`, `queued`, or `deferred`. `target_status` always
describes the destination Task, never the caller. `deferred` with reason
`target_awaiting_review` creates no activation; the caller completes honestly
and must not copy the destination's review state onto itself.
