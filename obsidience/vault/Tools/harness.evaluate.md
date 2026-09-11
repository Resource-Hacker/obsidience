---
type: tool
title: harness.evaluate
description: Evaluate one exact Runbook proposal in frozen Tool trials using proposal.
obsidience:
  binding: capability:harness.evaluate
  source: obsidience/harness/capabilities/harness/evaluate.py
  approved_at: '2026-09-09T17:56:32'
  provenance: proposed by Codex (task codex:implementation)
---

## Runtime

Evaluate one exact Runbook proposal in frozen Tool trials using proposal. Inputs, baseline, cases and acceptance are controller-bound. The candidate author cannot choose grades. Results are evaluation evidence, not approval or permission for live effects.

## Reference

Evaluate one exact Runbook proposal bound to the current Heimdall Audit.

Arguments: `{"proposal": "exact-pending-proposal.md"}`. Use the activation filename. No model, case, expectation, command or path overrides are accepted.

The controller checks the immutable case, accepted Task/Agent/Runbook/Skill/Tool revisions and exact candidate bytes. It compares the baseline and body-only candidate on matching training and held-out cases using the target Task's existing model and reasoning settings. Every trial Tool, including completion, is simulated through frozen responses in the existing executor; there is no live dispatch or effect. Model leases and foreground/STOP cancellation still apply.

Returns an immutable Source evaluation report, candidate identity and verdict: `passed`, `not_improved`, `regressed`, or `incomplete`. Passing requires complete valid coverage, all candidate cases passing, no regression, and strict training improvement. Timing and context measurements are separate; they do not prove workstation effects or exact historical replay.

Only a real returned Tool receipt and completed independent Audit support ordinary Review. Nothing is automatically accepted. Stale candidate, dependency, model configuration or evaluator revisions require fresh evaluation. Missing fixture responses and provider errors remain incomplete. This Tool cannot change models, author criteria, edit existing Source or invoke a shell.
