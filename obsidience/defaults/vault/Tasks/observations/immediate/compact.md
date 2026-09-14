---
type: task
title: Compact
obsidience:
  assignee: '[[Agents/Executive/Executive]]'
  context_threshold: 80
  model: auto
  reasoning_effort: low
  runbook: '[[Runbooks/observations/compact]]'
  taxonomy_path: observations/compact
  triggers:
  - observations.immediate.threshold
---

Condense the completed prefix of [Immediate Observations](/Agents/Executive/Observations/Immediate%20Observations/Immediate%20Observations.md)
into one cumulative Temporary Observation summary. Preserve the owner's current
goal, constraints and corrections, verified state, outstanding work, and the
minimum facts needed to continue naturally. Do not preserve hidden reasoning.

During an ongoing conversation, leave the latest two completed pairs exact. At
a real conversation boundary, compact the complete remaining tail before
promotion.

The default event trigger is 80 percent of the selected model's usable input
context. The owner may change that threshold or issue this Task immediately
from Executive Chat. Exact conversation turns remain in SQLite.
