---
type: task
title: Improve
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  model: auto
  reasoning_effort: xhigh
  runbook: '[[Runbooks/improve]]'
  enabled: true
  triggers:
  - task.create
  taxonomy_path: wiki/improve
---

Improve one bounded Knowledge Article from accepted graph knowledge and
preserved evidence. Success is one grounded staged revision or an honest
no-change result.
Inputs may bind exact candidate Articles, a broken reference or a real folder
missing its folder Article. An existing folder Article and native hierarchy
already provide structural coverage; a missing Markdown child list is not a
repair. Parent condensation and genuine editorial gaps remain in scope.
Missing facts are research gaps, never permission to invent.
