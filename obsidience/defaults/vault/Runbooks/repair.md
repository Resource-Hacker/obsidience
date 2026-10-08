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
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
---


1. Use [harness.status](/Skills/harness.status.md) to inspect current health. The triggering current warning is a lead; only this fresh controller snapshot governs action.
2. For an exact `repair_plan` row with operation `retry` or `settle`, call [harness.repair](/Skills/harness.repair.md) with only its exact `task` and `run_id`, or exactly `{"component":"hindsight"}` for a Hindsight component row. The controller can retain a fully attested public-page Source capture or recognize a proposal or Source handoff rejected before creation. It independently rejects uncertain actions, unaccounted downstream effects, pending Review and continuations. Do not infer permission from the Tool name or a failure message.
3. Re-read `harness.status` after each attempt, including a rejection. After an eligible attempt consumes the snapshot, the next decision exposes status until refreshed. Handle up to eight attempts per pass. Do not repeat an occurrence, retry Repair itself, or force a blocked entry. Eligible entries precede blockers.
4. Once fresh status has no eligible operation, or the eight-attempt budget is used, finish `task.complete` with `status: completed`. Name queued recoveries, remaining blockers, deferred eligible work and observed health. The controller automatically starts the next pass when actionable work remains after progress; it places unresolved blockers in the Review queue. A requeued target has not yet executed; never claim it completed from the requeue receipt.
5. If status is unavailable or invalid, or an eligible operation cannot be handled, finish `failed` with the concrete blocker. Missing receipts cannot prove safe replay. Preserve Source, prior runs and receipts; do not edit models, approve Review or clear a warning merely to claim healthy.

The existing scheduler owns automatic recovery through Task completion, startup and Source/Vault file-change events. It preserves foreground work and Task FIFO. A changed actionable state starts the next bounded pass; an unchanged unsuccessful pass or unavailable Repair becomes one persistent Review notification. Source integrity is inspected deterministically without a Check Task. Repeated reads and queue growth do not repeat a failed operation. Acknowledging a notification does not repair its cause or authorize replay.

When useful nonredundant findings should survive the activation, optionally use [observations.retain](/Skills/observations.retain.md) for one bounded unverified observation. Do not narrate routine recovery or record hidden reasoning.

Supported recovery distinguishes `retry` from `settle`. Both use the same exact task/run arguments and fresh status. Settlement retains an already queued Curate child, closes an invalidated maintenance lead after attested reads/pre-stage rejections, or retires an obsolete model event while retaining its manifest and proven pre-dispatch benchmark rejections. It advances one FIFO head without claiming downstream success. Ingest's reviewed create/update schema correction permits one additional retry only for an exact no-body archive rejection; it does not reset the general retry limit. No uncertain effect or active Review is replayed.


Hindsight memory recovery uses the same paired status and repair Tools. A `repair_plan` row with `component: hindsight` permits `harness.repair` with exactly {"component":"hindsight"}, instead of task/run arguments. It rechecks one failed upstream operation from that same-run snapshot, commits retry intent, and asks Hindsight to retry that exact operation once. It does not replay computer actions, create a new memory document, change models or approve wiki Knowledge. Refresh status after every attempt. Queued processing is not completion. The ordinary eight-attempt Repair budget remains; exhausted or unsupported memory faults appear in the existing Review notification queue. Hindsight emits success webhooks; the existing Harness health audit also checks backend failures without a Check Task or another scheduler.

Model characterization can resume once after an interrupted manifest-only pass. The controller attests the exact model event identity, original activation, immutable manifest and unchanged current artifact. It retains that manifest; any previous benchmark, configuration change or uncertain effect still blocks automatic retry. A superseded Repair pass with complete no-effect receipts is settled by the scheduler before a fresh health cycle; the Repair Tool never retries its own Task. Fixed Task dependencies are revalidated automatically without replaying completed work.

Failed Hindsight consolidations are separate from failed asynchronous operations. Fresh status also identifies recoverable consolidation batches. The same component repair records one attempt per unchanged source memory, calls Hindsight consolidation/recover, and starts its native deduplicated consolidate operation. It preserves original dates, memory records, existing observations and all wiki Review boundaries; repeated or uncertain attempts remain in Review.
