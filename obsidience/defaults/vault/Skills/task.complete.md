---
type: skill
title: Using task.complete
description: For an ordinary successful answer, status:completed and summary are sufficient.
obsidience:
  tool: '[[Tools/task.complete]]'
---

## Runtime

For an ordinary successful answer, status:completed and summary are sufficient. An evidence-bound no-change instead requires separate JSON args: {"status":"completed","outcome":"no_change","evidence":["the inspected evidence"],"summary":"why no change is warranted"}. Writing outcome or evidence inside summary does not set those fields. Use review only while this execution's proposal is pending; an actual owner approval permits completed with outcome:changed, and rejection or inaccessible inputs should be reported as failed. Do not stage a change merely to escape a completion error. Visual state verification describes current image evidence; it is not independent mechanical proof.

## Reference

Put the verified public answer, change, pending proposal or precise blocker in summary, within the Tool's limits. Choose completed for an established outcome, review for this execution's unresolved proposal or explicit acceptance gate, and failed for a terminal blocker. Pending proposals must remain review; a downstream Task's state is not its caller's result.

For evidenced no-change, pass `outcome:no_change` with concise inspected-input evidence. Never use it after staging/publishing. Use actual publication/disposition receipts; prose cannot replace publication or computer witnesses.

For computer operations, report only each requested target's verified effect/state. Existing state is not a new effect. Supply state verification only when the immediately received post-image visibly establishes the objective; otherwise fail or ask the clarification in summary. Do not relabel scope, fabricate evidence or replay uncertain input.

Inspect accepted. On false, retain the error and retry only after its precondition materially changes. An incomplete Merge needs the named redirect proposals before completion. Accepted recording does not independently certify the underlying facts.
