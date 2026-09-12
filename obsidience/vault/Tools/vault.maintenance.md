---
type: tool
title: vault.maintenance
description: Inspect accessible Knowledge for bounded maintenance candidates.
obsidience:
  binding: capability:vault.maintenance
  source: obsidience/harness/capabilities/vault/maintenance.py
---

## Runtime

Inspect accessible Knowledge for bounded maintenance candidates. No arguments. Candidate keys and revisions are controller evidence, not permission to edit. Use only the recommended accepted Task with the exact returned candidate fields. An empty result is a valid no-change finding. Native hierarchy already connects ancestors and descendants at every depth, including Agent-owned/checked-out Knowledge; those pairs are not missing-link candidates.

## Reference

Inspect one current vault snapshot and return a bounded, ranked list of
high-signal maintenance candidates with exact Article references, stable
candidate keys, structural signals, and the appropriate accepted Task. Current
checks cover duplicate and missing-link leads, exact broken references, missing
folder Articles, elapsed native OKF `stale_after` instants,
explicit native `status: deprecated`, authored `review_due` dates, and
`superseded_by` links. Stale evidence routes to Audit; explicit retirement or
supersession routes to Archive. Age or disconnectedness alone is never a finding.

`missing_index` identifies a real folder without its folder Article. An existing
folder Article and native hierarchy already provide structural child coverage;
missing Markdown child lists or per-child links are not findings. The parent
Article remains a readable condensation, not a generated table of contents.

Arguments: `{}`. The result reports counts and at most eight unclaimed
candidates. An exact accepted-input `candidate_revision` accompanies every
candidate. Completed explicit no-change decisions for the same revision are
suppressed using the existing run ledger; failures and summaries alone cannot
suppress work. It also reports a constant-size connectivity summary over accepted
Agent and Knowledge Articles: component count, isolated Article count, and the
largest component size. This topology includes native folder and Agent-scope
connections without writing duplicate hyperlinks. Semantic ranking still uses
actual content and authored links, not structural adjacency alone. Each missing-link candidate includes any isolated
endpoint refs, whether its endpoints occupy separate components, and at most
four exact shared-neighbor refs. Runtime observations and nonsemantic
Task/Runbook/Skill/Tool links are excluded from this topology.

Connectivity is descriptive. Disconnectedness, isolation, or a shared neighbor
does not establish a relationship or authorize a Link. The Tool is read-only
and deterministic; every candidate remains a lead for Curate, not a semantic
verdict or permission to edit.

Duplicate-by-similarity nomination excludes Knowledge folder Articles owned
by an actual accepted Agent. Ordinary leaf duplicates and the canonical Agent
versus ordinary shadow-role case remain eligible. This structural guard does
not suppress factual audits, improvements, or meaningful-link inspection.
Maintenance occurrence identity includes the inspected revision: unchanged
work remains deduplicated, while changed accepted inputs may be nominated again.
An evidenced settlement of an obsolete unused occurrence is not a semantic
no-change finding about the revised Articles.
