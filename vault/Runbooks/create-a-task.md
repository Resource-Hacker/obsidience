---
title: create-a-task
kind: runbook
owner_maintained: true
skills: ["[[Skills/reading-the-vault]]", "[[Skills/task-authoring]]"]
---
Procedure for proposing a new task.

1. `vault.search` for similar existing tasks; extend rather than duplicate.
2. Decide the shape: parts needing independently verifiable completion become
   ordered `subtasks` (max 9, each its own task note); otherwise one leaf
   task with a `runbook` link.
3. Write acceptance criteria as checkable statements.
4. `task.create` with the drafted body; complete with status "review".
