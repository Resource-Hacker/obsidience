---
type: runbook
title: Answer procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Executive/Executive]]'
  task: '[[Tasks/query]]'
  skills:
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/source.read]]'
  - '[[Skills/harness.status]]'
  - '[[Skills/task.create]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/observations.temporary.append]]'
---

## Runtime

Answer the assigned question from accepted Knowledge, current evidence and conversation. Search or read only a specific missing fact. Current health requires harness.status. A distinct research outcome may use task.create with wait_for_result:true where an exact user turn is bound. This question procedure grants no computer Tools; report an actual capability gap without inventing a routing/reclassification request. Finish through task.complete with a grounded answer or exact blocker.

## Reference

This shared fallback serves the existing Query definition. Specialist Agents retain their exact applicable Query Runbooks. Executive Chat and speech use [Executive instructions](/Agents/Executive/Executive.md) directly. Historical evidence explains previous outcomes and never authorizes replay or establishes current pixels. Do not use no_change as a generic answer status.
