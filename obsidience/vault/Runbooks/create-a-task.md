---
type: runbook
title: Generate task procedure
obsidience:
  approved_at: '2026-08-21T04:02:25'
  owner_maintained: true
  provenance: proposed by Codex (task research generation kit)
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.propose]]'
---

Synthesize one quality shared Task definition.

1. Frame one bounded outcome, its triggering context, expected assignee role, inputs, outputs, and objective completion evidence.
2. Search for similar Tasks and read the narrowest related Task and Runbook articles. Extend the existing semantic hierarchy rather than duplicating or flattening it.
3. Prefer one direct child level. Add another only when each child is an
   independently meaningful, verifiable outcome, as in the Observations
   lifecycle. Procedural stages belong in a Runbook. A container uses ordered
   `subtasks`; a leaf links one exact Runbook.
4. Write a nonempty bounded list of checkable acceptance criteria plus failure
   and review outcomes. Keep procedure in the Runbook and executable mechanics
   in Tools.
5. Use `vault.propose` with `action: create`, a target below `Tasks/`, the
   complete drafted body, and only reusable Task-definition metadata:
   `type: task`, one accepted `assignee`, one existing `taxonomy_path`, a
   nonempty `acceptance` list, exactly one accepted `runbook` or a nonempty list
   of accepted `subtasks`, plus optional ordered `triggers`, registered `model`,
   and `reasoning_effort`. Do not author runtime `params`, `status`, `schedule`,
   `enabled`, run IDs, results, or timestamps.
6. Finish with `review`, naming the proposed Task and its intended taxonomy
   placement. Generate → Task is the only path that authors reusable Task
   definitions; `task.create` activates an existing accepted Task and is not
   used here.

Quality gate: one outcome, narrow placement, deterministic completion evidence,
resolved Agent and Runbook or subtask references, valid event names and model
when supplied, no runtime occurrence state, and no procedure copied into the
Task.
