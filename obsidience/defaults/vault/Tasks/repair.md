---
type: task
title: Repair
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  model: auto
  reasoning_effort: xhigh
  runbook: '[[Runbooks/repair]]'
  taxonomy_path: harness/repair
  triggers:
  - harness.degraded
---

Complete one bounded recovery pass when the controller reports a new current Task warning or degraded state. Inspect current findings, apply only controller-supported recovery, inspect again after each attempted operation, and report the disposition and remaining blockers. The existing controller triggers recovery automatically on current warnings and continues after progress until no supported recovery remains.

A completed pass does not imply every fault is repaired or a queued target succeeded. Unsupported, exhausted or receipt-uncovered work appears automatically in the Review queue as a recovery notification. Acknowledgement does not clear the underlying warning. Repeated status reads and queue growth do not create another recovery event; the same occurrence receives at most one ordinary automatic retry; a specific implemented correction has its own single bounded recovery attempt.

Supported recovery distinguishes `retry` from `settle`. Both use the same exact task/run arguments and fresh status. Settlement retains an already queued Curate child, closes an invalidated maintenance lead after attested reads/pre-stage rejections, or retires an obsolete model event while retaining its manifest and proven pre-dispatch benchmark rejections. It advances one FIFO head without claiming downstream success. Ingest's reviewed create/update schema correction permits one additional retry only for an exact no-body archive rejection; it does not reset the general retry limit. No uncertain effect or active Review is replayed.
