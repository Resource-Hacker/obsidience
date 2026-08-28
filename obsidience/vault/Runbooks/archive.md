---
title: Archive procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Alexandria/Alexandria]]'
task: '[[Tasks/archive]]'
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/proposing-changes]]'
---

1. Select at most one ordinary Knowledge Article that appears stale,
   superseded, or no longer true. Never select an Agent, Tool,
   Skill, Task, or Runbook.
2. Read the candidate, its relevant accepted neighbors, and every exact Source
   citation required to establish staleness.
3. Confirm the candidate is not merely old: the replacement or contradiction
   must be explicit and current. Search for accepted inbound references.
4. If a retained article needs a correction first, stage that complete update
   before archival. Duplicate consolidation belongs to Merge. Do not
   conceal an unresolved conflict by archiving it.
5. Stage `vault.propose` with `action: archive`, the exact target, and a concise
   evidence-grounded reason. Approval will fail closed if an inbound reference
   remains.
6. Finish with `review` for one staged proposal, or `completed` with the exact
   no-change reason.
