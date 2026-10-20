---
type: tool
title: harness.optimize
description: Run the bound instruction optimization case with case_id. Returns measured
  comparisons and any candidate staged for Review; never changes the live Executive.
obsidience:
  binding: capability:harness.optimize
  source: obsidience/harness/capabilities/harness/optimize.py
---

## Runtime

Run the exact `optimization_case` bound to Heimdall Audit with `{"case_id":"<exact SHA256>"}`. Google Research Harness2 supplies one sequential Propose–Probe–Compose refinement step. AutoSaddler V2 supplies immutable candidate lineage and durable evaluation attempts; the Harness independently compares the final candidate with the baseline before selection for publication. An installation may explicitly select the retained AutoSaddler search backend for rollback. Executive and specialist trials run the ADK loop in an isolated in-memory session with no Hindsight recall or writeback; specialist captures from the retired JSON action loop are converted to native Tool calls. No trial operation has a live effect: a captured decision's read-only steps (Source and Article reads, search, validation) are answered from the current Vault, and every other call is intercepted before dispatch.

## Contract

Cases are independently registered or captured at the committed Capability boundary. Each evaluation uses five distinct decision cases repeated five times, giving 25 observations per baseline or full candidate. Automatic cases pair the triggering rejection with four accepted controls from four other runs of the same Task/Tool, using the actual executable completion/proposal contracts. Insufficient current evidence waits for more controls; the optimizer cannot duplicate cases or author grading criteria. A successful dry validation does not publish Knowledge or repeat an action.

The Audit-selected model proposes changes; the affected Agent/Task model runs evaluations through the existing model owner. Harness2 runs one refinement step at width one, with at most seven optimizer sessions including bounded correction attempts and optional reflection, a bounded persisted rollout budget and forty minutes of active job time across resumes. The final composed candidate and baseline receive independent full measurements; only training evidence reaches proposals or reflection. Compatible lessons become eligible only after committed instruction publication and the exact Audit receipt. The explicit AutoSaddler rollback backend retains its original three-iteration search and retry policy. Foreground demand cancels and joins inference; unpublished work can resume its exact checkpoint. STOP remains cancellation.

Repetitions are independent samples, so cases compare by pass counts. A candidate must pass every training trial, at least four of which the baseline failed, and at least three quarters of the held-out trials; the held-out cases may not pass less often in total, nor any one of them by two or more repetitions, nor average over half a Tool call more. Latency can reject a candidate only for Executive evaluated with reasoning `none`, using the existing 25-percent-plus-200-ms allowance. Specialists and Executive with reasoning enabled are judged on correctness without a latency rejection; timing remains visible. This follows the affected Agent/Task's reasoning setting, not Audit's. Only the instruction body can change, one whole paragraph or list item at a time (replaced, or added after another); links, metadata, grants and model settings remain frozen. The Tool returns `verdict`, `comparison`, `source_path`, `report_id`, and optionally a real `proposal`. That proposal is not deployment. After the Audit finishes, the existing Review authority revalidates the exact candidate and returned Tool receipt, then may publish under the owner's automatic instruction policy. Code and unsupported cases remain in Review; no ordinary wiki change is auto-approved by this capability.
