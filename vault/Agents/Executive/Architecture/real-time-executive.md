---
approved_at: '2026-08-27T14:09:26'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
title: Real-time Executive
---

The real-time Executive is one Obsidience execution surface, not another
Agent, harness, scheduler, memory store, or Tool authority. It operates under
[[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|local-first architecture]], whose
one-authority and local-model contract constrains its Task selection and Tool
execution.

Realtime has one reasoning pipeline. The model and reasoning effort selected on
[[Tasks/executive/realtime|Realtime]] remain the sole source of intent, Tool
selection, reasoning, and public answers. Pipecat and NVIDIA NeMo supply fixed
speech transport around that Task: Nemotron Speech Streaming EN 0.6B converts
the selected microphone stream into transcripts and manages turn boundaries;
Pocket TTS converts the completed public answer into speech on CPU. Neither is
an Agent or reasoning model. Pipecat's upstream `LocalAudioTransport` opens the
Hardware-selected microphone and speaker through process-scoped Pulse routing;
Obsidience adds no browser audio client, audio WebSocket, or custom
capture/playback processor. Realtime ready enables the OBSBOT SDK's persistent
microphone-during-sleep setting and Realtime off disables it.

Enabling the interface opens the Realtime Task and keeps it running until the
owner disables it or the runtime fails. Each final transcript is one execution
of that same Task through the normal activation compiler, so its Agent Identity,
Task, Tools, Skills, Runbook, retrieved Knowledge, Tool calls, and evidence all
follow the same graph path as scheduled or manually started work. The graph
therefore shows real work rather than an output-only animation mirror.

Typed Executive Chat and Realtime speech share one active exact conversation.
Its newest 80 turns remain in a bounded in-memory deque that rehydrates from the
existing SQLite runtime ledger. A finalized user turn is persisted before model
execution. An assistant turn is persisted only when the current generation
finishes with a nonempty public reply, and it names the exact user turn it
answers. Failed, blocked, interrupted, canceled, or generation-stale output is
not conversation history.

Only exact completed user-and-reply pairs may re-enter a later activation as a
bounded, transient, unverified conversation section. That section is not
indexed, does not participate in retrieval, and grants no Task or Tool authority.
Realtime start and stop preserve it. The owner's explicit New conversation
action rotates the active identity without deleting earlier SQLite rows. Each
completed pair also emits the ordinary `turn.complete` graph event; the
owner-enabled [[@agent/Temporary Observations|Temporary Observations]] Task may
distill a small semantic cache, while the exact transcript remains runtime state
rather than graph Knowledge.

Obsidience alone selects Tasks, retrieves Knowledge, authorizes and invokes
Tools, records evidence, and decides whether an outcome succeeded. Neither
the speech plumbing may invent a capability, execute an unbound Tool, persist
memory, or claim an external effect without verification. `task.complete`
remains owned by the Realtime button lifecycle.

While Realtime runs, the scheduler leaves autonomous specialist schedules and
triggers pending instead of claiming them. An exact `task.create` emitted from
Realtime may delegate a real peer Task to another Agent and carries immutable
creator provenance as the only exception. Causal ordering never makes that
peer a subtask. Turning Realtime off releases the pause without rewriting the
pending Tasks.

The microphone remains live while Pocket speaks, so a fresh acoustic turn can
cancel playback and the in-flight Task generation without waiting for output to
finish. NeMo may classify a short backchannel without interrupting. These are
speech-transport decisions, never Task, Tool, or Knowledge decisions.
