---
title: task-authoring
kind: skill
tools: [task.create]
---
How to author well-formed tasks.

- A task is WHAT, not HOW: put procedure in a runbook and reference it.
- Leaf tasks require a `runbook` link. Container tasks list ordered
  `subtasks` (max 9) and need no runbook — the decomposition is the how.
- Write acceptance criteria as checkable statements; they route the result to
  owner review.
- Search for an existing similar task first; extend rather than duplicate.
