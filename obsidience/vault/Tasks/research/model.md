---
type: task
title: Model
obsidience:
  assignee: '[[Agents/Darwin/Darwin]]'
  enabled: true
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/research/model]]'
  taxonomy_path: research/model
  triggers:
  - model.added
---

Characterize one newly registered or revised local model and leave it with an
attested Source manifest, measured valid hardware layouts, a bounded working
configuration, and a concise verified compatibility result.

Acceptance requires the exact event model to be inspected, every relevant
valid layout to have a preserved benchmark or explicit failure, the selected
settings to pass runtime validation without CPU offload, and the saved
Hardware selection to be restored.
