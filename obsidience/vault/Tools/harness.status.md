---
type: tool
title: harness.status
obsidience:
  binding: capability:harness.status
  source: obsidience/harness/capabilities/harness/status.py
---

Return one deterministic, read-only Obsidience health snapshot without shell
access.

Arguments: `{}`.

The result reports Article and graph counts, current Task runtime states,
pending reviews, Source file and integrity issue counts, and failure counts
from the 20 newest executions. Its top-level `degraded` status reflects Source
issues and unresolved current work: failed or blocked event commitments or
waiting queues, blocked Task configuration, and scheduled Tasks left in draft.
The same existing execution-state projection supplies current issues to the
Tasks pane. An idle terminal failure with no unresolved commitment or waiting
work remains historical evidence; it does not alone make current health
degraded. Bounded `task_issues` identify the exact Task, reason, and queue depth.
`recent_failures` never replaces that current-state assessment.

A valid degraded response is a successful diagnostic read. The Tool does not
diagnose causes, retry work, or repair anything, and it does not attest
subsystems absent from its snapshot.

`history` is a read-only projection of the existing execution ledger. It samples
at most 200 runs started in the last seven days, grouping exact Task and
recorded Runbook ref/hash. Its nested `tools` samples at most 400 controller
receipts started in the same window, grouping exact Task and Tool name/ref/hash.
Each reports sample counts, scan completeness, exclusions, and at most eight
findings with three run or call references and observed duration statistics.
Run findings require at least three completed/failed/blocked attempts, at least
two failed or blocked outcomes, and a failure ratio of at least 0.5. Tool
findings use the same minimum sample and ratio over returned/error/rejected
calls, counting error or rejected receipts. Other outcomes remain separate
and do not enter these denominators. A returned receipt is dispatch evidence;
it does not establish semantic success.

Historical findings apply to the recorded revision, not necessarily today's
revision. They neither change current health nor establish a root cause. An
empty finding list means no qualifying pattern in the eligible bounded sample,
not an attestation that every historical execution was healthy.

`source_files` counts the returned bounded page. `source_coverage` reports its
limit, returned count, live consistency and whether a next page exists; a full
page is not a Source integrity issue or a total inventory count.

`repair_plan` contains at most 12 current Task findings with exact Task, run,
occurrence identity, `retry` or `blocked` operation, and reason. It excludes
Repair itself and lists eligible work before blocked entries. This controller projection guides the separate Repair Task; the
status Tool remains read-only and grants no effect. Current `task_issue_count`
remains the complete count even when the plan is bounded.
