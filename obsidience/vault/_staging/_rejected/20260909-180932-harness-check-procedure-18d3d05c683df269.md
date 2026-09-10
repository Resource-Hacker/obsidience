---
type: knowledge
title: Harness check procedure
refinement:
  case_id: 4b83e1127329abd4eeccd1aef4e19a1b6377c28f59b0e4923a9193ec053a7e01
  case_sha256: 4b83e1127329abd4eeccd1aef4e19a1b6377c28f59b0e4923a9193ec053a7e01
  subject_task: Tasks/check
  subject_agent: Agents/Heimdall/Heimdall
  runbook_ref: Runbooks/check
  base_sha256: 48713eaa17d091a62698559309f7f40c1a4fdf8c8f319ad8ddd3954cfedea885
  evaluator_revision: 147bf4a038f3af15df613cef295ed96393f5b7a395f30ffd69771b6f31ffe6ec
obsidience:
  proposal: true
  action: update
  target: Runbooks/check.md
  agent: Darwin
  task: Tasks/generate/runbook
  run_id: 03d8659f14f0
  reason: Recorded Check reported a valid degraded snapshot accurately but its execution
    was recorded as failed; the body did not explicitly state that the snapshot's
    observed status is report content and never the Check's own outcome, nor require
    the completion summary to attribute the finding to the snapshot.
  review_class: article
  base_sha256: 48713eaa17d091a62698559309f7f40c1a4fdf8c8f319ad8ddd3954cfedea885
  authored_fields: []
  proposed_at: '2026-09-09T18:09:32'
  rejected_at: '2026-09-09T18:29:10'
  rejected_reason: 'Completed independent Audit 1465299ae15f found not_improved: baseline
    and candidate both passed 4/4 fixed cases. Preserve the accepted Check Runbook;
    retain immutable report 72b7718746bfb45d21184a3b306c5ee5ecf137393b7a5df9d6f90eabf2c9684f.'
---

## Prerequisites
- The active Task is Check and this Runbook's frozen metadata is the accepted authority; no other Tools are called.
- Selected Skill with its paired Tool: [Using harness.status](/Skills/harness.status.md) pairs `harness.status`. The built-in `task.complete` records the result.

## Ordered Actions
1. Follow [Using harness.status](/Skills/harness.status.md), then call `harness.status` exactly once with an empty argument object.
2. Preserve every returned status and count. From `task_issues`, name current unresolved Task work, its waiting event count, blocked configuration, and scheduled drafts. Keep `recent_failures` and any `history` and `history.tools` patterns separately as historical evidence, with the exact Task, recorded Runbook or Tool revision, eligible sample, unsuccessful outcomes, returned evidence references, and stated sample limits or omissions. Do not pool revisions, infer a current fault from old attempts, or treat an empty bounded sample as proof of complete health.
3. Decide the Check's own result before reporting it: the inspection succeeds when the single call returned a valid snapshot and the step 2 report can be completed. The snapshot's observed `status` value (`healthy` or `degraded`) is report content, never the Check's outcome.
4. Call `task.complete` once. Use `status: completed` for a successfully obtained and reported snapshot of either health value, and `status: failed` only in the failure branch below. In the summary, attribute the health finding to the snapshot rather than to the Check execution.

## Bounded Branches
- Valid `healthy` snapshot: `task.complete` with `status: completed`, reporting the healthy finding and relevant exact fields.
- Valid `degraded` snapshot: `task.complete` with `status: completed`, reporting the degraded finding and relevant exact fields. Do not claim to have repaired anything.
- Snapshot unavailable, invalid, or required report impossible: `task.complete` with `status: failed`, naming the diagnostic failure without inventing a root cause or a healthy result.

## Stop Conditions
- After the single `harness.status` call, stop further inspection; a repeat without a state change is not new evidence.
- After `task.complete`, stop. Make no mutation, repair, or Task creation.

## Completion Criteria
- A valid snapshot was obtained once and its required report is in the completion summary, with any degraded finding explicitly attributed to the observed snapshot.
- `task.complete` returned `accepted: true` with `completed` for a reported snapshot of either health value, or `failed` only for a diagnostic failure.

## Verification
- The completion summary states the observed `status` value and relevant exact fields, keeps `recent_failures` and history separate from the current finding, and records no mutation.
- The recorded result is `completed` exactly when a valid snapshot was obtained and reported, including degraded, and `failed` only when the snapshot or required report was unavailable, invalid, or impossible.

## Recovery
- An unavailable or invalid snapshot goes directly to the failed branch with the precise diagnostic blocker; do not retry to change the finding.
- If `task.complete` returns `accepted: false`, retain the error and correct a malformed argument only when the error identifies one; do not call `harness.status` again to change an already obtained finding.
