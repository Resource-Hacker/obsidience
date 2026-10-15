---
type: tool
title: harness.optimize
description: Run the bound AutoSaddler Executive optimization case with case_id. Returns
  measured comparisons and any candidate staged for Review; never changes the live
  Executive.
obsidience:
  binding: capability:harness.optimize
  source: obsidience/harness/capabilities/harness/optimize.py
---

## Runtime

Run the exact `optimization_case` bound to Heimdall Audit with `{"case_id":"<exact SHA256>"}`. Microsoft AutoSaddler V2 owns diagnosis, structured candidate edits, retries, evaluation and selection. Executive and specialist trials run the ADK loop in an isolated in-memory session with no Hindsight recall or writeback; specialist captures from the retired JSON action loop are converted to native Tool calls. No trial operation has a live effect: a captured decision's read-only steps (Source and Article reads, search, validation) are answered from the current Vault, and every other call is intercepted before dispatch.

## Contract

Cases are independently registered or captured at the committed Capability boundary. Each evaluation uses five distinct decision cases repeated five times, giving 25 observations per baseline or full candidate. Automatic cases pair the triggering rejection with four accepted controls from four other runs of the same Task/Tool, using the actual executable completion/proposal contracts. Insufficient current evidence waits for more controls; the optimizer cannot duplicate cases or author grading criteria. A successful dry validation does not publish Knowledge or repeat an action.

The Audit-selected model proposes changes; the affected Agent/Task model runs evaluations through the existing model owner. The native default is two session retries (three total attempts). Jobs allow three candidate iterations, a bounded rollout budget and forty minutes overall; the first accepted candidate ends the search. Foreground demand cancels and joins inference; unpublished work can resume its exact checkpoint. STOP remains cancellation.

Repetitions are independent samples, so cases compare by pass counts. A candidate must pass every training trial, at least four of which the baseline failed, and at least three quarters of the held-out trials; the held-out cases may not pass less often in total, nor any one of them by two or more repetitions, nor average over half a Tool call more. Latency can reject a candidate only for Executive evaluated with reasoning `none`, using the existing 25-percent-plus-200-ms allowance. Specialists and Executive with reasoning enabled are judged on correctness without a latency rejection; timing remains visible. This follows the affected Agent/Task's reasoning setting, not Audit's. Only the instruction body can change, one whole paragraph or list item at a time (replaced, or added after another); links, metadata, grants and model settings remain frozen. The Tool returns `verdict`, `comparison`, `source_path`, `report_id`, and optionally a real `proposal`. That proposal is not deployment. After the Audit finishes, the existing Review authority revalidates the exact candidate and returned Tool receipt, then may publish under the owner's automatic instruction policy. Code and unsupported cases remain in Review; no ordinary wiki change is auto-approved by this capability.
