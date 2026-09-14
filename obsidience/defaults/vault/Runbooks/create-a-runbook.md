---
type: runbook
title: Generate runbook procedure
obsidience:
  owner_maintained: true
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/observations.temporary.append]]'
---

Choose the procedure branch from the actual activation.

For `refinement_case`:
1. Read the controller's refinement binding, problem, originating execution and training examples. Treat the reconstruction and historical summary as evidence with their stated limits. Identify the first divergence and smallest general correction; do not memorize case IDs, fixed counts or expected answers.
2. Read the exact existing Runbook, target Task, selected Skills and paired Tools. Preserve the Runbook title, applicability and complete Skill set; its metadata and authority are frozen.
3. Draft one body-only revision with the exact sections `Prerequisites`, `Ordered Actions`, `Bounded Branches`, `Stop Conditions`, `Completion Criteria`, `Verification`, and `Recovery`. Explain each existing Skill with its exact reference. Use only its selected Tools and built-in `task.complete`. Keep the change general and concise.
4. Call `vault.propose` once with `action: update`, exact `output` path, unchanged title, complete revised body and concise causal reason. Omit metadata entirely. The controller binds the case and baseline and queues independent Heimdall evaluation.
5. Finish `review` with the proposal identity. No evaluation or acceptance has occurred yet. If no concrete correction is justified, finish `failed` with that limitation rather than inventing an improvement.

For a missing-procedure `task.assigned` activation, use the existing procedure below.

Generate one quality Agent-scoped Runbook when an assigned Task lacks an
applicable accepted procedure.

1. Read the event parameters: target Task, target Task article and hierarchy,
   target Agent, accepted shared Tools and their paired Skills, and the required output
   Runbook path. The supplied target article is the canonical Reader projection
   for both real Task Articles and synthetic `@library/Tasks/*` taxonomy Articles.
2. Read the canonical Task when it exists. For a synthetic taxonomy target,
   use the supplied article and hierarchy instead of trying to resolve it as a
   physical vault Article. An assigned container is a Task scope whose
   descendants come with it; generate its coordinating Runbook rather than
   rejecting it for being a container. Search for related real Tasks and
   Runbooks, then read only the relevant full Articles. Never invent a Tool or
   Capability absent from the supplied accepted catalog.
3. Select the minimal subset of catalog Skills needed for this Task's outcome
   and acceptance conditions, including its completion Tool. Read each selected
   canonical Skill and its paired Tool contract. The catalog offers candidates;
   it is not a grant to this Task and must not be copied wholesale. Skills only
   explain individual Tool use; the new Runbook must supply the task-specific
   sequence, branching, stop conditions, verification, and recovery behavior.
4. Draft one concise imperative Runbook for this exact Task and agent pairing.
   Use the exact sections `Prerequisites`, `Ordered Actions`, `Bounded Branches`,
   `Stop Conditions`, `Completion Criteria`, `Verification`, and `Recovery`.
   Cite only the selected Skills using their exact Article references. When an action is
   required, name that Skill's exact callable Tool ID, for example: follow
   `[Using vault.read](/Skills/vault.read.md)`, then call `vault.read`. Explicit
   Skill metadata determines the dependency set; prose never grants a Tool.
   Every called Tool must have its paired Skill in that set. Describe how the
   assigned Task executes after activation; the generated procedure must not
   mention the internal `task.assigned` event.
   Observations may preserve concise findings, decisions, blockers, and next
   actions, but never reasoning steps, hidden reasoning, or chain of thought.
5. Use `vault.propose` to create or update the required output path. Supply an
   explicit `metadata.skills` list of exact selected Skill refs, or its native
   `metadata.obsidience.skills` equivalent. Omission is invalid; neither the
   body nor the complete catalog is a substitute. The controller binds the
   exact `task` and `for_agent` applicability from this assignment. Complete
   with `review`, naming the proposal. The harness rejects completion without a
   validated proposal from this exact event. If the accepted catalog cannot
   satisfy the Task, complete with `failed` and report the missing capability
   rather than improvising it.

Quality gate: the Runbook must be executable by the target agent, scoped to one
Task, independently verifiable, and explicit about failure and recovery.

Approval preserves the explicitly selected Skills and exact Task/Agent
applicability. That accepted Runbook supplies its dependencies automatically;
it does not write `Agent.tools`, `Agent.skills`, or `Agent.runbooks`. The assigned
Task waits for approval rather than executing the proposal. Callable names in
the body never widen the set. Do not put YAML frontmatter in the body.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
