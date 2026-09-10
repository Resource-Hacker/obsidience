---
type: runbook
title: Generate tool procedure
obsidience:
  approved_at: '2026-08-21T04:02:30'
  owner_maintained: true
  provenance: proposed by Codex (task research generation kit)
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/vault.validate]]'
---

Synthesize one quality Tool contract and its mandatory paired Skill.

1. Read the requested capability, intended caller, inputs, outputs, side effects, and verification requirement. Search existing Tools, Skills, and Tasks; extend rather than duplicate.
2. Confirm that one thin executable entrypoint already exists at `obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`. Its binding must be `capability:<exact Tool title>`. A Tool is an interface to executable mechanism, not documentation. If the entrypoint is missing, stop with the exact implementation gap; this documentation Task neither authors code nor creates an implementation Task.
3. Draft the narrow Tool contract: exact arguments, bounded result, errors, side effects, targeting rules, verification evidence, and fail-closed behavior. Keep policy and multi-step procedure out of the Tool.
4. Use `vault.propose` with type `tool`, the exact Capability binding, and the
   one singular `source` entrypoint to create or update the Tool article. Never
   use plural `sources` for a Tool.
5. Draft its one paired Skill at `Skills/<exact dotted Tool title>.md`, with
   title `Using <exact dotted Tool title>` and exactly one singular
   `tool` field containing a wiki-link to that exact Tool Article. Explain only this Tool's
   prerequisites, exact arguments, returned evidence, typed failures, retry
   rules, and stop conditions. The Skill grants no other Tool and contains no
   task objective, multi-Tool procedure, policy, or general Knowledge.
6. Use `vault.propose` with type `skill` and that exact path, title, and
   singular Tool link. Finish with `review`, listing both proposals as one
   inseparable Capability pair. The Tool review admits the matching Skill in
   the same approval; an isolated Tool proposal fails closed.

Quality gate: one Tool, one Skill, one exact Capability binding, one singular
entrypoint, exact dotted basename parity, the `Using <tool.id>` Skill title, no
duplicate interface, no invented Capability, and enough contract detail for
deterministic validation. Supporting Modules remain internal plumbing.
