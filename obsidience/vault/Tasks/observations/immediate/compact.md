---
assignee: '[[Agents/Executive/Executive]]'
context_threshold: 80
kind: task
model: obsidience-gemma
params:
  curation_mode: compaction
  target_path: Agents/Executive/Observations/Temporary Observations
reasoning_effort: low
runbook: '[[Runbooks/observations/compact]]'
taxonomy_path: observations/immediate/compact
title: Compact
triggers:
- observations.immediate.threshold
---

Condense the completed prefix of [[Agents/Executive/Observations/immediate-observations|Immediate Observations]]
into one cumulative Temporary Observation summary. Preserve the owner's current
goals, decisions, constraints, unresolved questions, and the minimum facts
needed to continue naturally.

The default event trigger is 80 percent of the selected model's usable input
context. The owner may change that threshold or issue this Task immediately
from Executive Chat. Exact conversation turns remain in SQLite.
