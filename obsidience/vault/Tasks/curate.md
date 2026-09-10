---
type: task
title: Curate
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/curate]]'
  schedule: '*/30 * * * *'
  taxonomy_path: wiki/curate
---

Inspect one bounded wiki-maintenance snapshot and activate at most one exact
accepted maintenance Task named by the Curate Runbook. Success is one grounded
activation or an honest clean result. Activation records causal provenance in
the run ledger and never changes either Task's authored hierarchy.
