---
type: tool
title: task.complete
description: Finish with status:completed|failed|review and a factual summary.
obsidience:
  binding: capability:task.complete
  source: obsidience/harness/capabilities/task/complete.py
---

## Runtime

Use separate JSON argument fields. An ordinary answer is `{"status":"completed","summary":"the answer"}`. An evidence-bound no-change is `{"status":"completed","outcome":"no_change","evidence":["what was inspected"],"summary":"why no change is warranted"}`. Put these fields in args, never only in summary. A proposal already approved by the owner is no longer pending Review; completed/changed records that approval without another write.

Finish with status:completed|failed|review and a factual summary. Use outcome:no_change and concrete evidence only after a completed evidence-bound inspection. Computer outcomes require matching current controller evidence. State actions additionally require verification:{status:established,observation:<visible evidence>}. Intent, dispatch alone, historical prose and a target label do not prove completion. Never replay uncertain effects.

The controller constrains successful evidence-bound completion to separate outcome and evidence fields when no proposal or change is recorded. Failure remains available. This enforces argument structure, not the truth of supplied evidence.

## Reference

Record one terminal result for the active Task. Arguments: `{"status":"completed|failed|review","summary":str optional,"outcome":"changed|no_change" optional,"evidence":[str] optional,"verification":{"status":"established","observation":str} optional}`. Summary: at most 2,000 characters. Evidence: at most eight nonempty strings, each at most 500 characters. Verification has exactly the shown keys; observation is 1–1,000 characters. Unknown status or malformed evidence/verification is rejected.

Returns `accepted:true` with the recorded status/summary/outcome, or `accepted:false` with an error. Acceptance records a decision, not independent proof of semantic success. Interactive Chat/speech use summary as the public answer; completion leaves the speech connection available.

Unresolved proposals from this execution require review. Otherwise review requires an explicit Task acceptance gate; downstream Review does not change its caller's state. Generated-Runbook execution finishes review with its actual validated output proposal, or failed if none was staged. A `Merge is incomplete` archive blocker prevents review completion until the named referring-Article redirect proposals exist.

Evidence-bound execution with no staged, approved or reviewed proposal must explicitly complete with `outcome:no_change` and concrete evidence. No-change requires completed status and cannot accompany a pending, approved or reviewed proposal. Actual Auto-curate approval supports changed completion without pending Review. Evidence prose cannot replace controller witnesses.

Every Task using computer Tools must supply the matching actual execution receipts for each operation and target: fresh attached `computer.observe` image, active `window.activate` focus, `window.place` destination Surface and requested tile edges, or `application.launch` ready window. Screenshots do not prove focus/placement, and launch dispatch does not prove readiness. A verified existing state may complete without claiming a new effect.

computer.act declares `scope:input|state` in its actual Tool arguments. Input needs the latest acknowledged click and actual fresh post-image. State also needs the same target's post-action image attached to the immediately preceding model input and `verification:{"status":"established","observation":"Visible evidence for the requested state"}`. An intervening Tool or response consumes that immediate image evidence. Verification is the model's interpretation, not independent semantic proof. Intent, errors, history or acknowledgement alone cannot establish the requested state. Unclear targets finish failed with the clarification in summary; other failures name the blocker. These deliberate failures can be spoken without persisting a successful assistant turn. Never replay uncertain input.

A Source-bound Learn or Distill success requires the complete activating Source read and an attested cited handoff, or the supported explicit cited no-change outcome. Feed Ingest completion must attest the exact published item version or the actual bound pending Review, including required retention. Failed publication remains a failure; claiming success cannot bypass the Source, Feed or Review owner.
