---
type: task
title: Task
obsidience:
  assignee: '[[Agents/Darwin/Darwin]]'
  reasoning_effort: high
  runbook: '[[Runbooks/create-a-task]]'
---

The Task child of the top-level Generate Task. Darwin synthesizes one bounded
shared Task at the narrowest existing taxonomy placement with a nonempty list of
checkable acceptance criteria and exactly one accepted Runbook or an ordered set
of accepted subtasks. The proposal carries reusable definition metadata only,
never runtime parameters, status, scheduling state, or execution receipts.
