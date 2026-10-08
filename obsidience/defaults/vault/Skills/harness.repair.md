---
type: skill
title: Using harness.repair
description: Use only the exact recovery candidate from current evidence.
obsidience:
  tool: '[[Tools/harness.repair]]'
  requires:
  - '[[Skills/harness.status]]'
---

## Runtime

Use only an exact recovery candidate from fresh controller evidence. Report unsafe or stale candidates without clearing history or forcing admission.

## Reference

1. While executing Repair, call `harness.status` and select one `repair_plan` row with operation `retry` or `settle`.
2. Call `harness.repair` with exactly that row's `task` and `run_id`. A blocked row never authorizes a guessed repair.
3. Read status again after the attempt before any further recovery or completion. `requeued` means pending normal admission; `blocked` and `already_processed` require a truthful report, not another attempt.

The controller supports exact Source-bound research recovery when completed fetch receipts and immutable captured bytes agree. It retains those Sources; a subsequent ordinary fetch may capture an updated public page. Source capture is still an effect, never a read-only permission. It can also recognize exact proposal validation rejections before staging and missing-citation handoff rejections before Inbox creation, and complete read-only dispatch coverage even when the display trace was shortened.

No missing or uncertain receipt, pending Review, unaccounted downstream effect, or continuation can pass this path. A later run ID does not reset the one automatic retry per original occurrence. Do not retry Repair, edit Source, change models, approve changes or clear evidence. There are at most eight attempts per pass; then refresh status and report deferred work. The controller automatically continues after progress and sends unresolved blockers to the Review queue. Never invent an Article proposal to notify the owner.

Supported recovery distinguishes `retry` from `settle`. Both use the same exact task/run arguments and fresh status. Settlement retains an already queued Curate child, closes an invalidated maintenance lead after attested reads/pre-stage rejections, or retires an obsolete model event while retaining its manifest and proven pre-dispatch benchmark rejections. It advances one FIFO head without claiming downstream success. Ingest's reviewed create/update schema correction permits one additional retry only for an exact no-body archive rejection; it does not reset the general retry limit. No uncertain effect or active Review is replayed.


Hindsight memory recovery uses the same paired status and repair Tools. A `repair_plan` row with `component: hindsight` permits `harness.repair` with exactly {"component":"hindsight"}, instead of task/run arguments. It rechecks one failed upstream operation from that same-run snapshot, commits retry intent, and asks Hindsight to retry that exact operation once. It does not replay computer actions, create a new memory document, change models or approve wiki Knowledge. Refresh status after every attempt. Queued processing is not completion. The ordinary eight-attempt Repair budget remains; exhausted or unsupported memory faults appear in the existing Review notification queue. Hindsight emits success webhooks; the existing Harness health audit also checks backend failures without a Check Task or another scheduler.

Model characterization can resume once after an interrupted manifest-only pass. The controller attests the exact model event identity, original activation, immutable manifest and unchanged current artifact. It retains that manifest; any previous benchmark, configuration change or uncertain effect still blocks automatic retry. A superseded Repair pass with complete no-effect receipts is settled by the scheduler before a fresh health cycle; the Repair Tool never retries its own Task. Fixed Task dependencies are revalidated automatically without replaying completed work.

Failed Hindsight consolidations are separate from failed asynchronous operations. Fresh status also identifies recoverable consolidation batches. The same component repair records one attempt per unchanged source memory, calls Hindsight consolidation/recover, and starts its native deduplicated consolidate operation. It preserves original dates, memory records, existing observations and all wiki Review boundaries; repeated or uncertain attempts remain in Review.
