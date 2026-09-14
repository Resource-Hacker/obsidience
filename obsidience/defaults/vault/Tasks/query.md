---
type: task
title: Query
obsidience:
  assignee: '[[Agents/Executive/Executive]]'
  model: auto
  reasoning_effort: none
  runbook: '[[Runbooks/answer-the-user]]'
  taxonomy_path: executive/query
---

Answer a question addressed to the assigned Agent from the graph, current evidence, and its
activation packet. Existing specialist assignments select their own applicable Query Runbook. Chat and speech addressed to the [Executive Agent](/Agents/Executive/Executive.md) use its native DeepSeek session without activating a Task.

Completion means the owner receives a grounded answer, an evidenced finding
from a delegated research Task, or the exact unresolved blocker. Query is
interactive work and carries no speech-session or scheduled-maintenance lifecycle.
