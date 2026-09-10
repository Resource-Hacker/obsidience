---
type: tool
title: harness.repair
obsidience:
  binding: capability:harness.repair
  source: obsidience/harness/capabilities/harness/repair.py
---

Requeue one exact failed Task occurrence through the existing scheduler, only
from an active Repair Task and its current controller-observed health plan.

Arguments: `{"task": "Tasks/exact-task", "run_id": "exact-previous-run-id"}`.
Select an exact entry whose operation is `retry` from `harness.status.repair_plan`.
The controller revalidates the current occurrence, complete dispatch coverage,
absence of possible effects, retained Review and continuations within the
existing Task transaction. It preserves original inputs, waiting FIFO and
prior attempt evidence, and atomically records one automatic retry per original
Task/event/activation key. It never executes the target directly.

Results: `requeued`, `blocked`, or `already_processed`, with reasons and bounded
evidence. `requeued` means pending normal admission, not a completed target.
Every attempted eligible operation consumes the health inspection, including
race rejection; obtain a fresh `harness.status` before completing Repair.
Missing legacy receipts, possible effects, changed inputs, unsupported
configuration and a previous automatic retry block recovery. Repair cannot
retry itself, edit Source, change models or approve a Review.

One pass permits at most eight attempts, counted from the existing controller
Tool trace. Once that budget is used, read status again and report any deferred
eligible work for a later pass; do not attempt a ninth recovery.
