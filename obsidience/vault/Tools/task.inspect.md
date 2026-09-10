---
type: tool
title: task.inspect
obsidience:
  binding: capability:task.inspect
  source: obsidience/harness/capabilities/task/inspect.py
---

Read one accepted Task's current state and existing execution evidence. No
activation, retry, cancellation, approval, model call, or Source write occurs.

Arguments: `{"task":"Tasks/link","run_id":"optional exact execution ID"}`.
Without `run_id`, return up to five recent execution summaries. An exact ID
returns up to twelve Tool steps with bounded arguments/results, pinned Runbook
revision, model, status and timestamps. Truncation and invalid historic trace
are explicit. A missing execution is not inferred from another Task's history.

Completion means the execution ended; it does not prove its proposals were
approved or its factual claims were verified.
