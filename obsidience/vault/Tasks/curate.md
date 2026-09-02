---
assignee: '[[Agents/Alexandria/Alexandria]]'
kind: task
last_run: 13b76e532b98
model: obsidience-qwen38-27b-q8
reasoning_effort: xhigh
runbook: '[[Runbooks/curate]]'
schedule: '*/30 * * * *'
status: completed
status_updated: '2026-09-01T20:01:04'
summary: Inspected 60 Articles with vault.maintenance, found 8 unclaimed candidates,
  and activated only the first ranked Link candidate a90e34363e33c89c48ea for the
  two exact incident Articles. task.create returned started with target_status pending
  and hierarchy unchanged, recording Tasks/curate as causal provenance without creating
  a hierarchy relation.
taxonomy_path: wiki/curate
title: Curate
---

Inspect one bounded wiki-maintenance snapshot and activate at most one exact
accepted maintenance Task named by the Curate Runbook. Success is one grounded
activation or an honest clean result. Activation records causal provenance in
the run ledger and never changes either Task's authored hierarchy.
