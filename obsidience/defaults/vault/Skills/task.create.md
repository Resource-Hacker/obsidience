---
type: skill
title: Using task.create
description: Select an existing accepted outcome, not a new task name.
obsidience:
  tool: '[[Tools/task.create]]'
  requires:
  - '[[Skills/task.inspect]]'
---

## Runtime

Select an existing accepted outcome that explicitly accepts task.create, not a new task name. Executive Chat and voice already share one Task; choose its Tools directly instead of delegating routine computer operations. Pass one bounded objective and required bindings. Waiting for research does not transfer its Tools to the caller. Causal delegation does not create taxonomy children or authorize repeating earlier effects.

## Reference

Use `task.create` to activate one exact accepted Task from an authorized active
execution.

- Pass exactly `{"task": str, "params": object optional}`. `task` is one exact
  accepted Task ref. `params` may contain at most eight bounded instance fields;
  reserved provenance fields are ignored. If present, `candidate_key` must be a
  lowercase hexadecimal string of 12-64 characters and must remain unchanged
  for an idempotent repeat.
- Success returns `state: started|queued|deferred|processed`, the exact target
  ref, destination status, reason, unchanged hierarchy, creator ref, and queue
  position. `processed` means the same activation key already reached its
  current recorded state; `deferred` creates no new activation.
- The Tool activates an existing definition; it never changes that definition,
  its hierarchy, or its authored execution settings.
- Interactive Executive work may delegate Research Question or Learn when its
  Runbook requires that outcome. The controller derives interactive provenance
  from the active execution; never supply a field to bypass a scheduling pause.
- For an exact Research Question or Learn needed before the current objective
  can continue, add top-level `"wait_for_result": true`. The controller keeps
  a durable causal continuation, waits for the research and its Ingest outcome,
  then resumes the original objective without repeating already completed
  effects. This is not a parent/child Task relationship or a new Task definition.
- Maintenance candidate fields must come unchanged from the current
  `vault.maintenance` result. The controller validates and binds the exact
  candidate revision; do not invent evidence or infer it from a title.
- Stop on `Task activation rejected`, a missing or wrong-kind target, an
  unsupported activation event, oversized or invalid params, invalid candidate
  key, or incomplete caller context. Do not substitute a similar ref or invent
  missing definition fields.
