---
type: runbook
title: Audit procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  task: '[[Tasks/audit]]'
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/source.read]]'
  - '[[Skills/vault.validate]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/harness.status]]'
  - '[[Skills/task.inspect]]'
  - '[[Skills/review.inspect]]'
  - '[[Skills/harness.evaluate]]'
  - '[[Skills/observations.temporary.append]]'
  approved_at: '2026-09-09T17:57:05'
  provenance: proposed by Codex (task codex:implementation)
---

For an activation with `refinement_case` and `proposal`, follow [Using harness.evaluate](/Skills/harness.evaluate.md) and call `harness.evaluate` once with the exact bound filename. Do not edit the candidate, inspect its grading criteria or perform other maintenance in this branch. Report the actual verdict, paired counts and Source report path, including incomplete evidence or regressions. Finish `completed` after a real report, even for a negative verdict; finish `failed` only if no report can be obtained. This supports ordinary Review and never approves the proposal. Do not call `vault.propose` in this branch.

For other Audit activations, use the existing procedure below.

1. Use the exact candidate refs when this activation provides them. Otherwise
   call `harness.status` once and inspect one reported failed or blocked Task
   through `task.inspect`, selecting one exact returned execution ID for its
   Tool evidence. If none needs attention, call `review.inspect` once and
   inspect one pending proposal. If neither exists, use `vault.validate` once
   for a bounded graph-integrity result; do not invent a random audit scope.
2. Read the complete article, relevant accepted neighbors, and each relied-on
   Source. For a graph audit, call `vault.validate` once and inspect only the
   exact reported edges. For a contradiction audit, compare the complete claims
   rather than matching isolated phrases.
3. For a native OKF `stale_after` lead, compare its absolute timezone-aware
   instant with now. An elapsed deadline makes the retained Article stale;
   it is not proof of falsehood. Seek current source evidence before updating
   the Article or moving the deadline. Preserve documentary `resource` and
   `sources`; `generated.at` records a meaningful content change, not a
   verification event. Explicit `status: deprecated` is a retirement state.
   Compare scope, dates, qualifiers, attribution, and relationship direction.
   Classify evidence as supported, weakened, contradicted, or unresolved; classify
   graph edges as valid or broken. Do not reduce uncertainty to a binary verdict.
4. Treat reports and summaries as leads. `task.inspect` exposes actual Tool
   results; `review.inspect` exposes unaccepted proposal evidence, not approval.
   Missing, malformed or truncated evidence remains unresolved. Never invent
   the intended target of an ambiguous link, retry a failed effect, or turn
   a completed execution into a claim of accepted wiki changes.
5. If a grounded correction is necessary, stage at most one complete article
   update. Heimdall never approves his own proposal and never edits Source.
6. Finish with `review` for a proposal or `completed` with the exact scope,
   classification, counts, and citations. If an exact maintenance candidate
   needs no correction, use `outcome: no_change`, a short `summary`, and
   `evidence` listing the exact reads and observed justification;
   unresolved evidence is not a clean no-change verdict.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
