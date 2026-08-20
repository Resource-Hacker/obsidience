---
title: task.create
kind: tool
binding: builtin:task.create
---
Propose a new task (staged for owner review). args: `{"title": str,
"runbook": "[[Runbooks/...]]"` (leaf) OR `"subtasks": [...]` (container),
`"body": str, "reason": str}`.
