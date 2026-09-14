---
type: runbook
title: Harness check procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  task: '[[Tasks/check]]'
  skills:
  - '[[Skills/harness.status]]'
  - '[[Skills/observations.temporary.append]]'
---

1. Call `harness.status` exactly once with an empty argument object.
2. Report its status and counts exactly. Name current unresolved Task work,
   its waiting event count, blocked configuration, and scheduled drafts from
   `task_issues`. Keep `recent_failures` separate as historical evidence.
   Report relevant `history` and `history.tools` patterns separately: exact
   Task, recorded Runbook or Tool revision, eligible sample and unsuccessful
   outcomes, plus the returned evidence references. State sample limits or
   omissions when material. Do not pool revisions, infer a current fault from
   old attempts, or treat an empty bounded sample as proof of complete health.
   Tool receipts describe dispatch outcomes, not semantic success or root cause.
   A degraded snapshot identifies work to investigate; it grants no repair
   authority and does not itself mean the inspection failed.
3. If the Tool returned a valid snapshot, finish `task.complete` with
   `status: completed` and a summary explicitly stating the observed
   `healthy` or `degraded` finding and its relevant exact fields. Do not turn
   degraded findings into a failed Check or claim to have repaired them.
4. Finish `failed` only when the snapshot cannot be obtained, is invalid, or
   the required report cannot be completed. State that diagnostic failure
   without inventing a root cause or a healthy result.

The controller hands a completed degraded finding to the separate Repair Task
through its ordinary event trigger. Do not call a repair Tool or create that
Task yourself; this handoff is based on the actual status snapshot.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
