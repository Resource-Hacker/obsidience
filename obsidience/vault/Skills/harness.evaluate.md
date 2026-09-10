---
type: skill
title: Using harness.evaluate
obsidience:
  tool: '[[Tools/harness.evaluate]]'
  approved_at: '2026-09-09T17:56:32'
  provenance: proposed by Codex (task codex:implementation)
---

Use `harness.evaluate` only for the exact Runbook candidate bound to the current Audit.

1. Pass the activation `proposal` filename once. Omit every other field.
2. Read the real verdict and paired counts. `passed` means eligible for Review, not approved or deployed. `not_improved` preserves the baseline; `regressed` identifies lost behavior; `incomplete` lacks valid comparison evidence.
3. Report the exact Source report path, proposal identity and material limits. These are frozen Tool simulations with no workstation effects. Duration includes model admission and inference; mocked policy tests alone cannot establish model quality.
4. Finish Audit `completed` when a real report was obtained, including negative verdicts. If no report was obtained, finish `failed` with the exact blocker. Never call `vault.propose` to alter this candidate or its expectations.

The target Task owns its model and reasoning settings. STOP or foreground work interrupts the joined evaluation; an interrupted evaluation cannot support approval.
