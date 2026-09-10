---
type: skill
title: Using harness.status
obsidience:
  tool: '[[Tools/harness.status]]'
---

Use `harness.status` for one deterministic, read-only Obsidience health
snapshot.

- Pass exactly `{}` and invoke the Tool once per requested snapshot.
- Preserve every returned status and count. The result covers accepted graph
  size, Task execution state, pending reviews, Source integrity, and bounded
  execution history.
- Use `task_issues` for current unresolved event commitments, blocked queues,
  blocked configuration, or scheduled drafts. An idle failed attempt without
  outstanding work belongs to history; `recent_failures` alone cannot establish
  a current fault.
- `degraded` is an observed finding, not a Tool failure or root-cause diagnosis.
  A Check that successfully obtains and reports it completes with that finding.
  A healthy snapshot does not establish every Article's factual accuracy or
  the health of omitted subsystems.
- If the Tool is rejected or unavailable, report the diagnostic failure.
  Repeating a read without a state change is not additional evidence.
- Report `history` and `history.tools` separately from current health. Cite
  the exact Task and recorded Runbook or Tool revision for a relevant pattern,
  its eligible sample, observed failed/blocked or error/rejected counts, and
  returned run/call references. Do not combine unlike revisions.
- Preserve the seven-day start-time window and independent 200-run/400-call
  limits. Mention an incomplete scan, excluded records, or omitted findings
  when they limit a conclusion. No qualifying finding is not proof of a
  failure-free history. Cancelled, interrupted, review, started, and undispatched
  outcomes are not automatically failures. Tool receipt outcomes do not prove
  semantic success or diagnose the cause of a failure.

- Preserve `source_coverage`: `source_files` is the returned bounded page, not
  necessarily the complete inventory. Another live page is not an integrity fault.
- During Repair, use exact `repair_plan` entries only through the separately
  paired repair Skill. Obtain a fresh snapshot after every attempted eligible
  operation. Blocked findings remain evidence for disposition; they never grant
  shell, Source, model or Review authority. The plan is capped at 12 entries.
