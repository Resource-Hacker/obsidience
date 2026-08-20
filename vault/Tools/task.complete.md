---
title: task.complete
kind: tool
binding: builtin:task.complete
---
End the session and set the task result. args: `{"status":
"completed|failed|review", "summary": str}`. Always available; use "failed"
when the runbook cannot be followed, with the reason in the summary.
