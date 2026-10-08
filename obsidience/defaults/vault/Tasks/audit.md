---
type: task
title: Audit
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  model: auto
  reasoning_effort: xhigh
  runbook: '[[Runbooks/audit]]'
  triggers:
  - executive.optimize
  - harness.rejected
  taxonomy_path: harness/audit
  optimization_auto_apply: false
---

Improve Harness and Agent instructions through the upstream AutoSaddler engine. A receipt-proven rejection or failed execution triggers one bounded optimization job for the unchanged instruction definition and failure. Independently accepted decisions provide held-out controls; incomplete historical evidence produces a Review finding instead of guessed replay.

`executive.optimize` binds a registered Executive or specialist case. `harness.rejected` binds an automatically captured decision case. Both use the same capability, existing model reservations, scheduler, cancellation, immutable candidate journal and publication writer. AutoSaddler supplies its default two session retries; the adapter permits three candidate iterations within a fifteen-minute job budget.

When `optimization_auto_apply` is enabled by the owner, complete validated body-only Agent/Runbook improvements publish automatically after the Audit and exact Tool receipt finish. Metadata, grants, model settings, the optimizer's own authority and code remain outside automatic publication. Unresolved evidence or code problems go to Review. Wiki curation belongs to Alexandria.
