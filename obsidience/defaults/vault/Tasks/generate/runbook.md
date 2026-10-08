---
type: task
title: Runbook
obsidience:
  assignee: '[[Agents/Darwin/Darwin]]'
  model: auto
  triggers:
  - task.assigned
  - task.create
  reasoning_effort: xhigh
  runbook: '[[Runbooks/create-a-runbook]]'
---

The executable Runbook child of the top-level Generate Task. When an assigned
Task lacks an applicable accepted Runbook, a `task.assigned` graph event
activates this regular Task with the exact Task, target Agent, accepted shared
Tool+Skill catalog, and output Runbook ref. Darwin selects the minimal required
Skill set and stages the per-Agent procedure through ordinary Review. The
assigned Task waits until that procedure is approved; assignment alone grants
neither the entire catalog nor an unreviewed procedure.

Improvements to an existing procedure are owned by Heimdall Audit through AutoSaddler. Generate retains creation of genuinely missing Runbooks.
