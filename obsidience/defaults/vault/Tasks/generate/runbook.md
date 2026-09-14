---
type: task
title: Runbook
obsidience:
  assignee: '[[Agents/Darwin/Darwin]]'
  model: auto
  triggers:
  - task.assigned
  - runbook.refine
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

For an activation carrying `refinement_case`, Darwin investigates the supplied recorded failure and proposes one body-only improvement to the existing exact Runbook. The controller freezes its baseline, authority, model configuration and independent cases. The candidate enters Review and activates Heimdall Audit. Accepted behavior stays active until a passing independent evaluation and ordinary approval. This branch cannot add Tools or Skills, change models, author expectations or edit implementation Source.
