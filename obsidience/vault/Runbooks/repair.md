---
type: runbook
title: Harness repair procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  task: '[[Tasks/repair]]'
  skills:
  - '[[Skills/harness.status]]'
  - '[[Skills/harness.repair]]'
---

1. Use [harness.status](/Skills/harness.status.md) to inspect current health.
   The triggering Check is a lead; current controller findings govern action.
2. For an exact `repair_plan` entry with operation `retry`, use
   [harness.repair](/Skills/harness.repair.md) with only its `task` and `run_id`.
   Re-read `harness.status` after each attempted operation. Handle at most the
   bounded current plan, with at most eight attempts per pass; do not repeat
   an occurrence or retry Repair itself. Eligible entries precede blockers.
3. Preserve blocked entries with their exact reasons and prior run references.
   Missing receipts cannot prove safe replay. No shell, Source edits, model
   changes or Review decisions are available. Historical failures alone need
   no repair, and Source pagination is coverage rather than an integrity fault.
4. Once a fresh snapshot has no eligible operation, or eight attempts have
   used the pass budget, finish `task.complete` with
   `status: completed` and a concise summary of actions, remaining blockers,
   deferred eligible work, and observed health. Deferred work waits for a later
   Check pass. This completes the bounded recovery pass even when
   unsupported faults remain. A queued retry has not yet executed: explicitly
   preserve that distinction and never claim its target outcome succeeded.
5. If the required status read is unavailable or invalid, or an eligible
   operation cannot be handled, finish `failed` with the concrete blocker.
   Never clear evidence or claim healthy merely to satisfy completion.
