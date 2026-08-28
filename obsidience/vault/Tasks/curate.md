---
assignee: '[[Agents/Alexandria/Alexandria]]'
kind: task
last_run: f9e2ef8ebba6
model: obsidience-qwen38-27b-q8
reasoning_effort: xhigh
runbook: '[[Runbooks/curate]]'
schedule: '*/30 * * * *'
status: completed
status_updated: '2026-08-28T08:31:07'
summary: Curate inspected the current vault snapshot with vault.maintenance once.
  It checked 62 Articles and returned 0 unclaimed candidates (14 claimed), so no Task
  was activated. This is a clean no-change result.
taxonomy_path: wiki/curate
title: Curate
---

Inspect one bounded wiki-maintenance snapshot and activate at most one exact
accepted maintenance Task named by the Curate Runbook. Success is one grounded
activation or an honest clean result. Activation records causal provenance in
the run ledger and never changes either Task's authored hierarchy.
