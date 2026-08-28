---
approved_at: '2026-08-21T04:02:11'
kind: runbook
owner_maintained: true
provenance: proposed by Codex (task research generation kit)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/validating-the-vault]]'
title: Generate skill procedure
---

Synthesize the one usage Skill paired to an accepted leaf Tool.

1. Read the exact Tool article and verify that it is a leaf with one live `capability:<exact Tool title>` binding and one singular matching entrypoint. Search for an existing Skill paired through singular `tool:` metadata.
2. If the pair exists, improve that Skill instead of creating another. If the Tool is missing or non-executable, stop and request Tool generation; never invent its contract.
3. Write only specific usage guidance for this Tool: prerequisites, argument selection, returned evidence, error interpretation, safe retry rules, and stop conditions. Do not include a task-specific sequence or reference additional Tools; that belongs in a Runbook.
4. Use `vault.propose` to create or update the Skill with kind `skill` and an
   exact singular Tool link such as `Tools/vault.read`.
5. Finish with `review`, naming the proposal and the exact paired Tool.

Quality gate: exactly one accepted leaf Tool, one Capability entrypoint, exactly
one Skill, full contract coverage, and no Runbook policy disguised as a Skill.
