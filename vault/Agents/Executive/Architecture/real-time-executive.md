---
approved_at: '2026-08-25T18:08:41'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Real-time Executive
---

The real-time Executive is one Obsidience execution surface, not another
Agent, harness, scheduler, memory store, or Tool authority. It operates under
[[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|local-first architecture]], whose
one-authority, local-model, and exact-activation contract constrains its
models, Task selection, and Tool execution. It uses two local models because
conversation and planning have different timing requirements:

- Gemma 4 E2B Duplex receives the live stream, owns interruption timing, and
  is the only model allowed to publish the Executive's spoken response.
- DiffusionGemma 26B-A4B privately plans a response from the exact activation
  packet. Its output is advisory until the duplex receiver accepts it for the
  current, non-cancelled generation.

The duplex receiver is the same Gemma 4 E2B Duplex hardware component profiled in [[Agents/Executive/Architecture/current-executive-model--3745813a|Current Executive model]].

Every completed utterance enters the same Task selector and activation
compiler used by text, manual, scheduled, and event-triggered work. Enabling
the interface opens the single [[Tasks/executive/realtime|Realtime]] Task and
keeps it running until the owner disables the interface or the runtime fails.
The packet
order is Agent Identity, Task, Tools, Skills, Runbook, and up to five Relevant
Knowledge Articles. The graph therefore shows the exact Articles that are
active while the Executive thinks and speaks, and the completed turn returns
through the ordinary bounded Temporary Observations path. The packet's
construction rules are specified by
[[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]].

Obsidience alone selects Tasks, retrieves Knowledge, authorizes and invokes
Tools, records evidence, and decides whether an outcome succeeded. Neither
model may invent a capability, execute an unbound Tool, persist memory, or
claim an external effect without verification. During Realtime, a Tool call is
an ordinary step of that one Task rather than a synthetic Task of its own. The
planner may propose one exact Tool present in the current packet; the harness
validates and executes it off the receiver loop, and the returned observation
grounds the final response. `task.complete` remains owned by the Realtime
button lifecycle.

While Realtime runs, the scheduler leaves autonomous specialist schedules and
triggers pending instead of claiming them. An exact `task.create` emitted from
Realtime may delegate a real peer Task to another Agent and carries immutable
creator provenance as the only exception. Causal ordering never makes that
peer a subtask. Turning Realtime off releases the pause without rewriting the
pending Tasks.

The microphone transcript remains mutable until endpointing, so private
planner overlap is disabled in the production path. Loopback activation
requests run on a sidecar thread with a fresh bounded HTTP connection; they
never block the receiver's 80 ms interruption loop. For a Tool turn, E2B begins
the planner's short immediate sentence before the Tool observation returns;
the verified result follows on a fresh generation after that first segment is
finished. Mutable Moonshine transcripts never enable speculative overlap.
