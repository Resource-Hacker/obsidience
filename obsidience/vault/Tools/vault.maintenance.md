---
type: tool
title: vault.maintenance
obsidience:
  binding: capability:vault.maintenance
  source: obsidience/harness/capabilities/vault/maintenance.py
---

Inspect one current vault snapshot and return a bounded, ranked list of
high-signal maintenance candidates with exact Article references, stable
candidate keys, structural signals, and the appropriate accepted Task. Current
checks cover duplicate and missing-link leads, exact broken references, missing
or underlinked folder indexes, elapsed native OKF `stale_after` instants,
explicit native `status: deprecated`, authored `review_due` dates, and
`superseded_by` links. Stale evidence routes to Audit; explicit retirement or
supersession routes to Archive. Age or disconnectedness alone is never a finding.

Arguments: `{}`. The result reports counts and at most eight unclaimed
candidates. An exact accepted-input `candidate_revision` accompanies every
candidate. Completed explicit no-change decisions for the same revision are
suppressed using the existing run ledger; failures and summaries alone cannot
suppress work. It also reports a constant-size connectivity summary over accepted
Agent and Knowledge Articles: component count, isolated Article count, and the
largest component size. Each missing-link candidate includes any isolated
endpoint refs, whether its endpoints occupy separate components, and at most
four exact shared-neighbor refs. Runtime observations and nonsemantic
Task/Runbook/Skill/Tool links are excluded from this topology.

Connectivity is descriptive. Disconnectedness, isolation, or a shared neighbor
does not establish a relationship or authorize a Link. The Tool is read-only
and deterministic; every candidate remains a lead for Curate, not a semantic
verdict or permission to edit.
