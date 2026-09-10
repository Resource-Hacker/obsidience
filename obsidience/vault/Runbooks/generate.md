---
type: runbook
title: Generate procedure
obsidience:
  approved_at: '2026-08-21T04:02:05'
  owner_maintained: true
  for_agent: '[[Agents/Darwin/Darwin]]'
  provenance: proposed by Codex (task research generation kit)
  subrunbooks:
  - '[[Runbooks/create-a-tool]]'
  - '[[Runbooks/create-a-skill]]'
  - '[[Runbooks/create-a-task]]'
  - '[[Runbooks/create-a-runbook]]'
  task: '[[@library/Tasks/generate]]'
---

Quality procedures for synthesizing graph-native objects.

Each child Runbook owns exactly one output type: Tool, Skill, Task, or Runbook. Tools and Skills remain strict one-to-one shared pairs, Tasks are shared outcome definitions, and Runbooks are synthesized for the specific agent that must execute the Task. New generation procedures belong as meaningful siblings beneath this node.
