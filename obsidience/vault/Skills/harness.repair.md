---
type: skill
title: Using harness.repair
description: Use only the exact recovery candidate from current evidence.
obsidience:
  tool: '[[Tools/harness.repair]]'
---

## Runtime

Use only the exact recovery candidate from current evidence. Inspect whether a prior effect already happened before any retry. Report unsafe or stale candidates instead of clearing their history or forcing admission.

## Reference

Use `harness.repair` only while executing Repair after reading `harness.status`.

- Choose exactly one returned `repair_plan` row with operation `retry` and pass
  its exact `task` and `run_id`. Do not invent a recovery operation for a blocked row.
- Treat `requeued` as pending work, not repaired semantics. Preserve its receipt
  and exact target reference in the report. `blocked` and `already_processed`
  require a truthful disposition, not a repeated attempt.
- After any eligible attempt, read `harness.status` again before another
  recovery decision or completion. A stale snapshot is no longer completion evidence.
- A later target run ID does not authorize another automatic retry of the same
  occurrence. Missing receipts, possible effects, retained Review and
  continuations remain blockers for explicit disposition.
- Never use this interface to retry Repair, clear evidence, approve changes,
  edit Source or alter models. Further unsupported work remains reported.

One pass permits at most eight attempts, counted from the existing controller
Tool trace. Once that budget is used, read status again and report any deferred
eligible work for a later pass; do not attempt a ninth recovery.
