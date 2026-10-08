---
type: runbook
title: Audit procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  task: '[[Tasks/audit]]'
  skills:
  - '[[Skills/harness.optimize]]'
---

Use [AutoSaddler](/Skills/harness.optimize.md) for Harness and Agent instruction improvement.

1. The controller binds `optimization_case` from an independently registered case or a receipt-proven incident. Call `harness.optimize` exactly once with that value as `case_id`. The upstream engine owns diagnosis, candidate edits, retries, comparison and selection.
2. Report the returned verdict, comparison and Source report. A returned `proposal` is a measured instruction candidate: finish `review` with its filename so the controller can verify the completed Audit receipt. The installation's `optimization_auto_apply` setting controls automatic publication after that verification.
3. Without a proposal, finish `completed` for a real report, including a negative finding. If the Tool returns an error without a report, finish `failed` with that error. Never repeat the optimizer in the same activation or manufacture a case ID.

There is no separate inspection-and-definition-proposal procedure. Do not call `vault.propose`, author grades, or interpret a simulated Tool as a live action. The existing Repair Task owns deterministic recovery and exact receipt-based retry/settlement. Missing evidence, unsupported implementations and exhausted optimization remain visible in Review. Code changes require review; ordinary wiki recommendations retain their own Review policy.
