---
type: task
title: Archive
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/archive]]'
  enabled: true
  triggers:
  - task.create
  taxonomy_path: wiki/archive
---

Retire one explicitly deprecated or demonstrably superseded ordinary Knowledge
Article without deleting its content, immutable Source, or history. Success is
one safe archive proposal or an evidence-grounded no-change result. Native OKF
`status: deprecated` records retirement; an elapsed `stale_after` alone calls for
revalidation through [Audit](/Tasks/audit.md), not archival by age.
