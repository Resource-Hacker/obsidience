---
approved_at: '2026-08-21T04:02:40'
kind: runbook
owner_maintained: true
provenance: proposed by developer (task research/generate/runbook)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/proposing-changes]]'
title: Generate runbook procedure
---

Generate one quality agent-scoped Runbook when a Task is checked out.

1. Read the event parameters: target Task, target Task article and hierarchy,
   target agent, checked-out Tools, their paired Skills, and the required output
   Runbook path. The supplied target article is the canonical Reader projection
   for both real Task Articles and synthetic `@library/Tasks/*` taxonomy Articles.
2. Read the canonical Task when it exists. For a synthetic taxonomy target,
   use the supplied article and hierarchy instead of trying to resolve it as a
   physical vault Article. A checked-out container is an executable scope whose
   descendants come with it; generate its coordinating Runbook rather than
   rejecting it for being a container. Search for related real Tasks and
   Runbooks, then read only the relevant full articles. Never invent a Tool or
   capability that is not in the event's checked-out set.
3. Read each listed canonical Skill and its paired Tool contract. Skills only
   explain individual Tool use; the new Runbook must supply the task-specific
   sequence, branching, stop conditions, verification, and recovery behavior.
4. Draft one concise imperative Runbook for this exact Task and agent pairing.
   Use the exact sections `Prerequisites`, `Ordered Actions`, `Bounded Branches`,
   `Stop Conditions`, `Completion Criteria`, `Verification`, and `Recovery`.
   Name only the listed `Skills/...` Articles and never name or grant Tools
   directly. Describe how the checked-out Task executes after activation; the
   generated procedure must not mention the internal `task.checkout` event.
   Observations may preserve concise findings, decisions, blockers, and next
   actions, but never reasoning steps, hidden reasoning, or chain of thought.
5. Use `vault.propose` to create or update the required output path. Complete
   with `review`, naming the proposal. The harness rejects completion without a
   validated proposal from this exact event. If the available Tools cannot
   satisfy the Task, complete with `failed` and report the missing capability
   rather than improvising it.

Quality gate: the Runbook must be executable by the target agent, scoped to one
Task, independently verifiable, and explicit about failure and recovery.

The harness binds the listed canonical Skills into accepted frontmatter when
the owner approves the proposal; do not put YAML frontmatter in the body.
