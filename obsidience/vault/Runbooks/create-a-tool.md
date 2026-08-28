---
approved_at: '2026-08-21T04:02:30'
kind: runbook
owner_maintained: true
provenance: proposed by Codex (task research generation kit)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/validating-the-vault]]'
title: Generate tool procedure
---

Synthesize one quality Tool contract and its mandatory paired Skill.

1. Read the requested capability, intended caller, inputs, outputs, side effects, and verification requirement. Search existing Tools, Skills, and Tasks; extend rather than duplicate.
2. Confirm that one thin executable entrypoint already exists at `obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`. Its binding must be `capability:<exact Tool title>`. A Tool is an interface to executable mechanism, not documentation. If the entrypoint is missing, stop with the exact implementation gap; never publish a fake Tool or invent runtime work.
3. Draft the narrow Tool contract: exact arguments, bounded result, errors, side effects, targeting rules, verification evidence, and fail-closed behavior. Keep policy and multi-step procedure out of the Tool.
4. Use `vault.propose` with kind `tool`, the exact Capability binding, and the
   one singular `source` entrypoint to create or update the Tool article. Never
   use plural `sources` for a Tool.
5. Draft its one paired Skill explaining specifically how to invoke this Tool, choose arguments, interpret results, and handle its errors. The Skill grants no other Tool and contains no task workflow.
6. Use `vault.propose` with kind `skill` and the exact singular Tool link for
   the Skill. Finish with `review`, listing both proposals as one inseparable
   Capability pair. The Tool review admits the matching Skill in the same
   approval; an isolated Tool proposal fails closed.

Quality gate: one Tool, one Skill, one exact Capability binding, one singular
entrypoint, no duplicate interface, no invented Capability, and enough contract
detail for deterministic validation. Supporting Modules remain internal plumbing.
