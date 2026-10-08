---
type: task
title: Archive
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  model: auto
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
revalidation through [Improve](/Tasks/improve.md), not archival by age.
Report the exact freshness blocker for Curate or owner routing; Archive does not
activate another Task.
