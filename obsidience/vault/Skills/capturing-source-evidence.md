---
title: Capture source evidence
kind: skill
tool: '[[Tools/source.ingest]]'
---
Use `source.ingest` immediately after acquiring material and before summarizing
it. Preserve the exact relevant payload, the direct reference, the real capture
time, and the correct media type. Keep one independently attributable source in
each capture. Never clean up, rewrite, merge, or silently complete missing
source text before capture. A failed or partial acquisition should be reported
honestly rather than stored as complete evidence.

A genuinely new capture emits `source.added` and queues Darwin's existing Learn
research Task. An identical re-capture returns the existing citation and does
not create another event. Supporting captures made inside that Learn occurrence
join the active commitment rather than recursively queueing it.

Carry the returned `source://` citation into the finding and use
`source.handoff` for the final physical Inbox drop. The citation proves which
immutable material informed the synthesis; it does not prove that the material
is true.
