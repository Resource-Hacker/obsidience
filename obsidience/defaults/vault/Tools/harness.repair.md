---
type: tool
title: harness.repair
description: Request one receipt-safe recovery with exact task and run_id from current
  status evidence.
obsidience:
  binding: capability:harness.repair
  source: obsidience/harness/capabilities/harness/repair.py
---

## Runtime

Request one verified recovery using exact `task` and `run_id` from current status. The controller rejects stale or uncertain effects. Requeue admission does not establish the requested outcome.

## Reference

Arguments: `{"task": "Tasks/exact-task", "run_id": "exact-previous-run-id"}`. Requires an active execution with this Tool granted through its paired Skill and a same-run `harness.status` plan. Heimdall uses the ordinary Repair Task.

The existing Task owner rechecks exact original parameters, activation identity, complete durable dispatch coverage, pending Review, continuations and prior automatic retries. It can admit read-only work, exact proposal rejections before staging, and exact missing-citation handoff rejections before Inbox creation. For Source-bound Learn, it can explicitly retain completed public-page captures after reconstructing their full returned result and verifying its durable hash against immutable Source bytes. Partial or uncertain captures remain blocked; ordinary startup reconciliation does not gain this exception.

The transaction preserves the original occurrence, waiting FIFO and prior attempt evidence, and commits one separate automatic-retry receipt per Task/event/activation key, including retained capture references. It queues normal execution, never executes the target or rewrites its old receipt. A subsequent normal fetch may capture an updated page while the previous Source remains intact.

Results: `requeued`, `settled`, `blocked`, or `already_processed`, with reasons and bounded evidence. Each eligible attempt consumes its health inspection, including a rejected race. Refresh `harness.status` before another operation or completion. One pass allows eight attempts; the existing controller continues with another pass when progress leaves eligible work. Unsupported or exhausted recovery is surfaced as a Review notification, separate from Article approval. Unknown effects, missing coverage, pending Review and continuations block recovery. Changed inputs require an attested settlement; a previous retry requires a specific implemented correction. Repair cannot retry itself, edit Source, alter models or approve changes.

Supported recovery distinguishes `retry` from `settle`. Both use the same exact task/run arguments and fresh status. Settlement retains an already queued Curate child, closes an invalidated maintenance lead after attested reads/pre-stage rejections, or retires an obsolete model event while retaining its manifest and proven pre-dispatch benchmark rejections. It advances one FIFO head without claiming downstream success. Ingest's reviewed create/update schema correction permits one additional retry only for an exact no-body archive rejection; it does not reset the general retry limit. No uncertain effect or active Review is replayed.


Hindsight memory recovery uses the same paired status and repair Tools. A `repair_plan` row with `component: hindsight` permits `harness.repair` with exactly {"component":"hindsight"}, instead of task/run arguments. It rechecks one failed upstream operation from that same-run snapshot, commits retry intent, and asks Hindsight to retry that exact operation once. It does not replay computer actions, create a new memory document, change models or approve wiki Knowledge. Refresh status after every attempt. Queued processing is not completion. The ordinary eight-attempt Repair budget remains; exhausted or unsupported memory faults appear in the existing Review notification queue. Hindsight emits success webhooks; the existing Harness health audit also checks backend failures without a Check Task or another scheduler.

Model characterization can resume once after an interrupted manifest-only pass. The controller attests the exact model event identity, original activation, immutable manifest and unchanged current artifact. It retains that manifest; any previous benchmark, configuration change or uncertain effect still blocks automatic retry. A superseded Repair pass with complete no-effect receipts is settled by the scheduler before a fresh health cycle; the Repair Tool never retries its own Task. Fixed Task dependencies are revalidated automatically without replaying completed work.
