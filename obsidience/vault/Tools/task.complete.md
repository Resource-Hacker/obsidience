---
type: tool
title: task.complete
obsidience:
  binding: capability:task.complete
  source: obsidience/harness/capabilities/task/complete.py
  approved_at: '2026-09-06T01:04:57'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

End one active Task execution with one terminal result. Interactive answers
from typed Chat or speech use this same completion; `summary` carries the
verified public answer. Completing work does not close the speech connection.

Arguments: `{"status": "completed|failed|review", "summary": str optional,
"outcome": "changed|no_change" optional, "evidence": [str] optional, "verification": {"status":"established", "observation":str} optional}`.
The summary is capped at 2,000 characters. Evidence is capped at eight nonempty
500-character entries. Pass one exact status; an unknown status is rejected.

The summary records the verified outcome, proposal, or exact blocker. An
`accepted: true` result records the decision; it does not independently prove
that the Task acceptance condition was satisfied.

For Computer Use, `completed` requires the executor's actual verified Tool
result for the requested outcome and, when explicitly bound, the exact canonical
application. Tile placement requires matching attested tile edges as well as
the destination Surface. The executor rejects an explicitly contradictory
application target before dispatch; a focused observation can resolve normally
but its actual result must still match. A screenshot cannot prove focus or placement,
launch dispatch cannot prove readiness, and input acknowledgement cannot prove
an in-client postcondition. Model-authored `evidence` never substitutes for this
controller witness. An unclear target finishes `failed` with the clarification
question in `summary`; a blocked operation finishes `failed` with its exact
blocker. Those deliberate public results can be spoken without persisting a
successful assistant conversation turn.

`review` is valid only when this exact execution staged at least one unresolved
proposal or the Task Article has an explicit authored acceptance gate. A
downstream Task's review state does not put the caller in review.

An evidence-bound execution with no pending or approved change must explicitly
finish `completed` with `outcome: no_change` and concrete evidence. A no-change
outcome is rejected when any proposal remains pending or a change was approved.
An owner Auto-curate approval is controller evidence for `outcome: changed` and
does not leave the Task in a zombie Review state.

An archive with an exact `Merge is incomplete` blocker cannot complete review.
The Tool returns the missing referring Article refs so the active Merge can
stage their redirects and retry completion.

Controller-bound computer outcomes apply to every Task: Query cannot complete a computer action. For action, computer_scope must explicitly be input or state. Input requires the latest acknowledged click and actual fresh post-image. State additionally requires a current post-action image attached to the immediately preceding model input, plus verification: {"status":"established","observation":"visible evidence supporting the requested application state"}. The verification object has exactly status and observation, with 1-1,000 observation characters. It records the model's interpretation; it does not turn input delivery into independently verified semantic truth. An intervening Tool or response consumes that immediate image evidence. If the state is not established, complete failed with the actual limit; never manufacture evidence or relabel success. Historical receipts cannot satisfy a current outcome.
