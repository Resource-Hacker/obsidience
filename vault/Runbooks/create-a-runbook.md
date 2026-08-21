---
approved_at: '2026-08-21T04:02:40'
event: task.checkout
kind: runbook
owner_maintained: true
provenance: proposed by developer (task research/generate/runbook)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/proposing-changes]]'
title: runbook
---

Generate one quality agent-scoped Runbook when a Task is checked out.

1. Read the event parameters: target Task, target agent, checked-out Tools,
   their paired Skills, and the required output Runbook path.
2. Read the canonical Task when it exists. Search for related Tasks and
   Runbooks, then read only the relevant full articles. Never invent a Tool or
   capability that is not in the event's checked-out set.
3. Read each listed canonical Skill and its paired Tool contract. Skills only
   explain individual Tool use; the new Runbook must supply the task-specific
   sequence, branching, stop conditions, verification, and recovery behavior.
4. Draft one concise imperative Runbook for this exact Task and agent pairing.
   Include prerequisites, ordered actions, bounded branches, stop conditions,
   completion criteria, verification, and recovery. Name only the listed
   Skills and never grant Tools directly.
5. Use `vault.propose` to create or update the required output path. Complete
   with `review`, naming the proposal. If the available Tools cannot satisfy
   the Task, propose a fail-closed Runbook that reports the missing capability
   rather than improvising it.

Quality gate: the Runbook must be executable by the target agent, scoped to one
Task, independently verifiable, and explicit about failure and recovery.

The harness binds the listed canonical Skills into accepted frontmatter when
the owner approves the proposal; do not put YAML frontmatter in the body.
