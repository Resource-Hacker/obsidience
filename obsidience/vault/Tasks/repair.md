---
type: task
title: Repair
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  model: obsidience-qwen38-27b-q8
  reasoning_effort: xhigh
  runbook: '[[Runbooks/repair]]'
  taxonomy_path: wiki/repair
  triggers:
  - harness.degraded
---

Complete one bounded recovery pass after a degraded harness Check: inspect
current findings, apply only controller-supported recovery, inspect again after
an attempted operation, and report the verified disposition and remaining
blockers. A completed pass does not imply all harness faults were repaired or
that a queued target outcome succeeded. Unsupported or receipt-uncovered work
remains intact for explicit disposition.
