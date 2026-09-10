---
type: runbook
title: Improve procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  task: '[[Tasks/improve]]'
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/source.read]]'
  - '[[Skills/vault.propose]]'
---

1. Use the exact `candidate_refs` and `candidate_signals` when supplied; otherwise
   select one bounded weak Knowledge Article. Read it and relevant accepted
   neighbors. For `missing_index`, `candidate_signals.index_ref` is the proposed
   new folder Article of a real folder; condense only its supplied accepted
   children. An existing folder Article and the native hierarchy already
   provide structural child coverage. Do not synthesize per-child Markdown
   tables of contents or links to reproduce that hierarchy. Preserve the
   parent's useful condensation and assess only genuine editorial gaps; do
   not create a second index or move Articles to fake hierarchy.
2. Read any exact `source://` citations needed to support the change. Never use
   a search snippet or an unattested claim as evidence.
3. Choose only the smallest fitting operation: cite, copyedit, condense,
   expand, categorize, update, retitle, or split. These are
   procedure branches, not separate queueable Tasks or a Lint family.
   A broken reference is an exact unresolved path, not a similar title. Repair
   it only with evidence of its intended target; otherwise report the gap.
4. Preserve meaning, provenance, qualifiers, and useful links. Do not alter raw
   Source material or silently invent missing facts.
5. Stage one complete `update` or `create` proposal with exact evidence in the
   reason. Duplicate consolidation belongs to Merge, and a
   missing relationship belongs to Link rather than this general editorial
   procedure.
6. Finish with `review` when a proposal exists; otherwise complete with the
   exact scope checked and reason no safe improvement was available. Use
   `outcome: no_change` only after inspecting the exact candidate and confirming
   that no correction is needed, with that reason in `summary` and exact observed
   findings in the `evidence` list. Missing evidence
   is unresolved, not a clean verdict.
