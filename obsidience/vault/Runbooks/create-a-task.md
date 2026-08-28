---
approved_at: '2026-08-21T04:02:25'
kind: runbook
owner_maintained: true
provenance: proposed by Codex (task research generation kit)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/proposing-changes]]'
title: Generate task procedure
---

Synthesize one quality shared Task definition.

1. Frame one bounded outcome, its triggering context, expected assignee role, inputs, outputs, and objective completion evidence.
2. Search for similar Tasks and read the narrowest related Task and Runbook articles. Extend the existing semantic hierarchy rather than duplicating or flattening it.
3. Prefer one direct child level. Add another only when each child is an
   independently meaningful, verifiable outcome, as in the Observations
   lifecycle. Procedural stages belong in a Runbook. A container uses ordered
   `subtasks`; a leaf links one exact Runbook.
4. Write checkable acceptance criteria, failure and review outcomes, parameter limits, and any required reasoning effort. Keep procedure in the Runbook and executable mechanics in Tools.
5. Use `vault.propose` with `action: create`, a target below `Tasks/`, the
   complete drafted body, and typed Task metadata including the exact `runbook`
   or `subtasks`. Finish with `review`, naming the proposed Task and its intended
   taxonomy path. Generate → Task is the only path that authors reusable Task
   definitions; `task.create` activates an existing accepted Task and is not
   used here.

Quality gate: one outcome, narrow placement, deterministic completion evidence, no hidden event object, and no procedure copied into the Task.
