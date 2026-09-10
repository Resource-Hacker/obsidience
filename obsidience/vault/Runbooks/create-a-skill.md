---
type: runbook
title: Generate skill procedure
obsidience:
  approved_at: '2026-08-21T04:02:11'
  owner_maintained: true
  provenance: proposed by Codex (task research generation kit)
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/vault.validate]]'
---

Synthesize the one usage Skill paired to an accepted leaf Tool.

1. Read the exact Tool article and verify that it is a leaf with one live `capability:<exact Tool title>` binding and one singular matching entrypoint. Search for an existing Skill paired through singular `tool:` metadata.
2. If the pair exists, improve that Skill instead of creating another. If the Tool is missing or non-executable, stop and request Tool generation; never invent its contract.
3. Write only specific usage guidance for this Tool: prerequisites, exact
   arguments, returned evidence, typed failure interpretation, safe retry
   rules, and stop conditions. Do not include a task objective, multi-Tool
   sequence, policy, general Knowledge, or reference to another Tool; those
   belong in their own ontology kinds.
4. Name the physical Article `Skills/<exact dotted Tool title>.md`, set its
   title to `Using <exact dotted Tool title>`, and give it exactly one singular
   `tool` field containing a wiki-link to that exact Tool Article. The Skill filename and
   paired Tool filename therefore have the same dotted basename while their
   distinct kinds and titles remain explicit.
5. Use `vault.propose` to create or update that exact Skill Article.
6. Finish with `review`, naming the proposal and the exact paired Tool.

Quality gate: exactly one accepted leaf Tool, one Capability entrypoint, exactly
one Skill, exact dotted basename parity, the `Using <tool.id>` title, full
single-Tool contract coverage, and no Runbook policy disguised as a Skill.
