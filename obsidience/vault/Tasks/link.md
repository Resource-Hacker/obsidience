---
type: task
title: Link
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  enabled: true
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/link]]'
  taxonomy_path: wiki/link
  triggers:
  - task.create
---

Determine whether one exact candidate pair has a missing, meaningful
relationship. When it does, stage the smallest contextual Article update that
creates the useful graph edge and explains why it exists. When the relationship
would be generic, redundant, or unsupported, complete with no change.
