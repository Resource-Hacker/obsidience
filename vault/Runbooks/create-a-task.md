---
title: create-a-task
kind: runbook
owner_maintained: true
---
Procedure for proposing a new task.

1. `search_vault` for similar existing tasks; extend rather than duplicate.
2. Decide decomposition: if any part needs independently verifiable
   completion, it deserves its own task note linked with `part_of`; otherwise
   keep one note. Cap decomposition at 5–9 parts.
3. Every task must link a `runbook:` and an `assignee:` charter. If the
   runbook is missing, still create the task — it will block as
   `awaiting-runbook`, which is correct.
4. Write acceptance criteria as checkable statements.
5. `create_task` with the drafted body; finish with status `review`.
