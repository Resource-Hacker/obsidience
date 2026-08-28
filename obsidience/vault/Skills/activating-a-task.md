---
title: Activating a task
kind: skill
tool: '[[Tools/task.create]]'
---
Call `task.create` only when the active Runbook names one exact accepted Task
that explicitly accepts `task.create` events. Pass `task` as the exact ref and
put only bounded instance data in `params`. Preserve an exact deterministic
candidate key when one is provided so repeated activations remain idempotent.

Never supply or invent a title, objective, acceptance test, Runbook, Agent,
model, reasoning effort, or taxonomy placement. Those are authored on the
target Task Article. Activation records causal provenance but does not alter
hierarchy. Generate → Task is the only path that authors reusable Task
definitions, using `vault.propose`.

Interpret the result precisely. `started` and `queued` are successful
activations. `deferred` with `target_awaiting_review` means the destination is
still owned by an earlier review and no new activation was created. Complete
the calling Task with an honest deferred/no-change result; never mark the
caller `review` merely because `target_status` is `review`.
