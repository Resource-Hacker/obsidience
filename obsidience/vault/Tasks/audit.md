---
type: task
title: Audit
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/audit]]'
  schedule: 20 */6 * * *
  triggers:
  - task.create
  - runbook.proposed
  taxonomy_path: wiki/audit
  approved_at: '2026-09-09T17:57:04'
  provenance: proposed by Codex (task codex:implementation)
---

Audit one bounded evidence or graph-integrity question. Success is a precise
supported, weakened, contradicted, unresolved, valid, or broken result backed
by the accepted graph and exact Source material.
Scheduled Audit checks one current failed Task, pending proposal or bounded
Article question; a peer activation binds its exact candidate Article refs.

A `runbook.proposed` activation evaluates one exact Darwin-authored Runbook candidate against independently frozen cases. Success is a complete, accurately reported comparison, including a negative verdict. Publication remains ordinary Review; Audit cannot author the candidate or its grading expectations.
