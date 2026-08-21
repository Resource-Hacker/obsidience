---
approved_at: '2026-08-21T04:02:25'
kind: runbook
owner_maintained: true
provenance: proposed by Codex (task research generation kit)
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/task-authoring]]'
title: task
---

Synthesize one quality shared Task definition.

1. Frame one bounded outcome, its triggering context, expected assignee role, inputs, outputs, and objective completion evidence.
2. Search for similar Tasks and read the narrowest related Task and Runbook articles. Extend the existing semantic hierarchy rather than duplicating or flattening it.
3. Choose the shape: independently verifiable stages become ordered `subtasks` (maximum nine, each a real Task); otherwise create one leaf linked to one exact Runbook. Parent index nodes carry children and no runnable state.
4. Write checkable acceptance criteria, failure and review outcomes, parameter limits, and any required reasoning effort. Keep procedure in the Runbook and executable mechanics in Tools.
5. Use `task.create` with the drafted body and exact `runbook` or `subtasks`. Finish with `review`, naming the proposed Task and its intended taxonomy path.

Quality gate: one outcome, narrow placement, deterministic completion evidence, no hidden event object, and no procedure copied into the Task.
