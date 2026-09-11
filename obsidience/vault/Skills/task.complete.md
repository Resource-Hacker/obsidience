---
type: skill
title: Using task.complete
description: For an ordinary successful answer, status:completed and summary are sufficient.
obsidience:
  tool: '[[Tools/task.complete]]'
  approved_at: '2026-09-06T01:05:00'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

## Runtime

For an ordinary successful answer, status:completed and summary are sufficient. Do not use no_change as a generic success code. Report a blocker rather than an unobserved result. Visual state verification describes current image evidence; it is not independent mechanical proof.

## Reference

Put the verified public answer, change, pending proposal or precise blocker in summary, within the Tool's limits. Choose completed for an established outcome, review for this execution's unresolved proposal or explicit acceptance gate, and failed for a terminal blocker. Pending proposals must remain review; a downstream Task's state is not its caller's result.

For evidenced no-change, pass `outcome:no_change` with concise inspected-input evidence. Never use it after staging/publishing. Use actual publication/disposition receipts; prose cannot replace publication or computer witnesses.

For Computer Use, report only the bound target's verified effect/state. Existing state is not a new effect. Supply state verification only when the immediately received post-image visibly establishes the objective; otherwise fail or ask the clarification in summary. Do not relabel scope, fabricate evidence or replay uncertain input.

Inspect accepted. On false, retain the error and retry only after its precondition materially changes. An incomplete Merge needs the named redirect proposals before completion. Accepted recording does not independently certify the underlying facts.
