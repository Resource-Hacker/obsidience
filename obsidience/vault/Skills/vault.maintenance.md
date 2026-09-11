---
type: skill
title: Using vault.maintenance
description: Treat candidates as leads.
obsidience:
  tool: '[[Tools/vault.maintenance]]'
---

## Runtime

Treat candidates as leads. Forward only the exact recommended Task, candidate key, revision, refs, kind and signals. A stale revision requires a new inspection. Disconnectedness or similar titles alone do not justify links or merges.

## Reference

Use `vault.maintenance` to inspect one current accepted-vault snapshot for
bounded structural maintenance leads.

- Pass exactly `{}` and invoke the Tool once for the snapshot being evaluated.
- Success returns JSON containing checked, total, claimed, and unclaimed counts
  plus a bounded connectivity summary and at most eight ranked candidates.
  Each candidate's `recommended_task`, `candidate_key`, `candidate_revision`, `refs`, score, and
  signals form one inseparable result record.
- Forward the exact candidate identity, revision, kind and signals when the
  active Runbook authorizes a peer Task. Never recompute or guess these fields.
  `unchanged_no_change_count` reports previously inspected unchanged leads,
  not new repairs. Broken references and missing folder Articles route to Improve; explicit
  elapsed native `stale_after` and review dates route to Audit; native
  `status: deprecated` and explicit supersession route to Archive. Each
  destination independently verifies its lead.
- `missing_index` means the folder Article is absent. Existing folder Articles
  and native hierarchy already represent child coverage. Do not turn missing
  Markdown child lists into repair work or synthesize per-child tables of
  contents; parent prose remains a useful condensation.
- For a missing-link lead, read `connectivity.isolated_endpoint_refs` as exact
  zero-neighbor endpoints, `connectivity.separate_components` as no existing
  semantic path between the endpoints, and `connectivity.shared_neighbor_refs`
  as at most four exact Agent or Knowledge Articles adjacent to both. Task,
  Runbook, Skill, Tool, and runtime-observation links do not count as semantic
  neighbors.
- Candidates are read-only leads, not semantic verdicts or edit authority. An
  empty candidate list is a successful clean result for this snapshot, even if
  the descriptive connectivity summary reports multiple components or isolated
  Articles.
- Stop on malformed JSON, missing candidate identity fields, duplicate refs, or
  an unavailable snapshot. Repeating the same call without a vault change is
  not new evidence.

Duplicate-by-similarity nomination excludes Knowledge folder Articles owned
by an actual accepted Agent. Ordinary leaf duplicates and the canonical Agent
versus ordinary shadow-role case remain eligible. This structural guard does
not suppress factual audits, improvements, or meaningful-link inspection.
Maintenance occurrence identity includes the inspected revision: unchanged
work remains deduplicated, while changed accepted inputs may be nominated again.
An evidenced settlement of an obsolete unused occurrence is not a semantic
no-change finding about the revised Articles.
