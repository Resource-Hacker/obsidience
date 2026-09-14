---
type: task
title: Learn
obsidience:
  assignee: '[[Agents/Darwin/Darwin]]'
  enabled: true
  reasoning_effort: high
  runbook: '[[Runbooks/research/learn]]'
  taxonomy_path: research/learn
  triggers:
  - source.added
  - task.create
---

Close one useful gap in the accepted graph with bounded direct-source research.
When `source.added` activates this Task, research that exact Source. When an
accepted caller uses `task.create`, research its exact bounded objective. Finish by
dropping at most one cited synthesis into the physical Source Inbox; do not
stage an intermediate owner Review.
