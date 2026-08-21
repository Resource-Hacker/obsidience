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
- '[[Skills/task-authoring]]'
- '[[Skills/validating-the-vault]]'
title: tool
---

Synthesize one quality Tool contract and its mandatory paired Skill.

1. Read the requested capability, intended caller, inputs, outputs, side effects, and verification requirement. Search existing Tools, Skills, and Tasks; extend rather than duplicate.
2. Confirm that a real executable `builtin:<name>` binding already exists. A Tool is an interface to executable mechanism, not documentation. If no binding exists, use `task.create` to propose the bounded implementation Task and stop with review status; never publish a fake Tool.
3. Draft the narrow Tool contract: exact arguments, bounded result, errors, side effects, targeting rules, verification evidence, and fail-closed behavior. Keep policy and multi-step procedure out of the Tool.
4. Use `vault.propose` with `metadata: {kind: tool, binding: builtin:<name>}` to create or update the Tool article.
5. Draft its one paired Skill explaining specifically how to invoke this Tool, choose arguments, interpret results, and handle its errors. The Skill grants no other Tool and contains no task workflow.
6. Use `vault.propose` with `metadata: {kind: skill, tool: [[Tools/<tool>]]}` for the Skill. Finish with `review`, listing the Tool before the Skill as the required approval order.

Quality gate: one real binding, one Tool, one Skill, no duplicate interface, no invented capability, and enough contract detail for deterministic validation.
