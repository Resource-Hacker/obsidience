---
for_agent: '[[Agents/Alexandria/Alexandria]]'
kind: runbook
owner_maintained: true
skills:
- '[[Skills/inspecting-maintenance-candidates]]'
- '[[Skills/activating-a-task]]'
task: '[[Tasks/curate]]'
title: Curate procedure
---

1. Call `vault.maintenance` exactly once. Do not perform an unbounded manual
   scan or treat a similarity signal as a conclusion.
2. If no unclaimed candidate exists, complete with the checked Article count
   and a clean no-change result.
3. Select only the first ranked candidate and map its exact recommendation:
   - `Merge` → `Tasks/merge`;
   - `Link` → `Tasks/link`.
   Call `task.create` exactly once with:
   `{"task":"<mapped exact Task ref>","params":{"candidate_key":"<exact key>","candidate_refs":["<exact ref>","<exact ref>"]}}`.
   Do not add an objective, acceptance test, Runbook, Agent, model, or title;
   those belong to the accepted destination Task and its Runbook.
4. Complete Curate after `task.create` returns `started` or `queued`. If it
   returns `deferred` with reason `target_awaiting_review`, complete Curate with
   an honest deferred/no-change result: the destination remains responsible for
   its own review, and Curate owns no proposal. Never mark Curate `review` for a
   destination's state, activate more than one Task in a single execution, or
   perform Merge or Link work inside Curate.

The activated Task retains its authored WIKI placement. Its activation packet
records Curate as causal provenance, not as a parent or subtask.
