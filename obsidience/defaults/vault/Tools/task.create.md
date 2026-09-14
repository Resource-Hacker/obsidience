---
type: tool
title: task.create
description: Activate one accepted Task with task and bounded params.
obsidience:
  binding: capability:task.create
  source: obsidience/harness/capabilities/task/create.py
---

## Runtime

Activate one accepted Task with task and bounded params. This does not author a definition or grant its Tools to the caller. Question/Learn may use wait_for_result:true for a current user turn; await_publication:true additionally waits for durable publication. Preserve the exact objective and returned activation identity. Queued work is not a completed result. Routine Executive operations use its available Tools directly; task.create is for a distinct accepted specialist outcome.

## Reference

Activate one exact accepted Task required by the active Runbook. Arguments:
`{"task": "Tasks/<exact ref>", "params": {<up to 8 fields>} optional,
"wait_for_result": boolean optional}`.
The target must explicitly accept `task.create`. Interactive Executive work
may delegate the accepted Research Question or Learn Tasks through its
Task-derived Tool and Runbook contracts. During an enabled speech connection,
the controller's interactive provenance admits that exact delegation while
autonomous specialist work remains pending. Other callers retain their
authored Tool and Runbook contracts.

An optional `candidate_key` inside `params` must be 12-64 lowercase hexadecimal
characters and makes repeated activation idempotent. Caller-supplied provenance
fields are discarded and replaced by the active Task and run identities.

The target keeps its authored Agent, Runbook, model, reasoning effort,
acceptance conditions, and hierarchy. The activation packet and run ledger
record which Task activated it as causal provenance; that never creates a
parent, child, or subtask relation.

This Tool never authors or revises a Task definition.

`wait_for_result: true` is available only for Research Question or Learn.
It preserves the original objective as a causal continuation, waiting for
research delivery and accepted Ingest or an evidenced no-change outcome.
It does not create a hierarchical subtask or replay earlier effects.

The result state is `started`, `queued`, `deferred`, or `processed`.
`processed` means the same activation key already reached its current recorded
state. `target_status` always describes the destination Task, never the caller.
`deferred` with reason `target_awaiting_review` creates no activation; the
caller completes honestly and must not copy the destination's review state
onto itself.
