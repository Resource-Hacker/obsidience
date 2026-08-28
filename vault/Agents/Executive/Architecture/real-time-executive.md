---
approved_at: '2026-08-27T17:41:35'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Real-time Executive
---

The real-time Executive is one Obsidience execution surface, not another
Agent, harness, scheduler, memory store, or Tool authority. It operates under
[[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|local-first architecture]],
whose one-authority and local-model contract constrains Task selection and Tool
execution. Its durable Knowledge context is the accepted vault described by
[[Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a|LLM-wiki knowledge pattern]].

Realtime has one reasoning pipeline. The model and reasoning effort selected on
[[Tasks/executive/realtime|Realtime]] remain the sole source of intent, Tool
selection, reasoning, and public answers. Pipecat and NVIDIA NeMo supply fixed
speech transport around that Task: Nemotron Speech Streaming EN 0.6B converts
the selected microphone stream into transcripts and manages turn boundaries;
Pocket TTS converts the completed public answer into speech on CPU. Neither is
an Agent or reasoning model. Pipecat's upstream LocalAudioTransport opens the
Hardware-selected microphone and speaker through process-scoped Pulse routing;
Obsidience adds no browser audio client, audio WebSocket, or custom
capture/playback processor. Realtime ready enables the OBSBOT SDK's persistent
microphone-during-sleep setting and Realtime off disables it.

Enabling the interface opens the Realtime Task and keeps it running until the
owner disables it or the runtime fails. Each final transcript executes that same
Task through the normal activation compiler described by
[[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]],
which assembles the visible Thinking Packet. Agent Identity, Task, Tools,
Skills, Runbook, retrieved Knowledge, and
[[Agents/Executive/Observations/immediate-observations|Immediate Observations]]
form one visible Thinking Packet. The exact packet refs drive graph activity, so
the graph shows what the model received rather than a second animation-only
selection.

Typed Executive Chat and Realtime speech share one active exact conversation.
Its newest 80 turns remain in a bounded in-memory deque that rehydrates from the
SQLite execution store, while SQLite retains the complete public history. A
finalized user turn is persisted before model execution. An assistant turn is
persisted only when the current generation finishes with a nonempty public
reply, and it names the exact user turn it answers. Failed, blocked,
interrupted, canceled, or generation-stale output is not conversation history.

The active context window is one transient, unverified Immediate Observations
Knowledge Article. It has retrieval disabled and always rides in the active
Executive Thinking Packet by exact Article identity. It contains the newest
cumulative Temporary Observation summary followed by exact completed
user-and-reply pairs after that summary's sequence boundary. It grants no Task,
Tool, Policy, or durable Knowledge authority. Enabling Realtime rotates once to
a fresh conversation without waiting on prior-session maintenance. Typed Chat
and speech share that identity until the next Realtime enable or the owner's
explicit New Conversation action. The outgoing Chat session is retained for
finalization when Realtime ends, preserving startup latency. Disabling Realtime
does not rotate on its own, and rotation never deletes earlier SQLite rows.

At 80 percent of the selected Task model's usable input context by default,
[[Tasks/observations/compact|Compact Immediate Observations]] runs as
an ordinary Executive Task with its authored Runbook, Skills, Tools, model, and
reasoning effort. The owner may choose 60, 70, 80, or 90 percent or press
Compact immediately. The Task condenses only the completed prefix into one
cumulative Temporary Observation Article. Tool output remains provisional until
the Task completes; failed, blocked, canceled, or stale attempts cannot advance
the context boundary. Exact public turns remain in SQLite. Executive Chat and
Realtime do not emit the retired per-turn Temporary Observation Task.

Temporary summaries are transient, unverified working context. At an explicit
Chat conversation rotation, or after Realtime fully stops,
[[Agents/Alexandria/Alexandria|Alexandria]]'s
[[Tasks/observations/promote|Promote Temporary Observations]] Task force-
compacts the final completed prefix, archives the exact bound Temporary bundle
in immutable Source, and stages only justified Knowledge creates or updates for
owner review. Merge and Link remain ordinary peer Tasks when needed. Accepted
Knowledge in the normal graph is the durable context; Source archival and
pending proposals do not create a parallel memory store or accepted truth.

Obsidience alone selects Tasks, retrieves Knowledge, authorizes and invokes
Tools, records evidence, and decides whether an outcome succeeded. Neither
speech plumbing nor Observation projection may invent a capability, execute an
unbound Tool, persist durable Knowledge, or claim an external effect without
verification. Task completion for the long-running Realtime session remains
owned by the Realtime button lifecycle.

While Realtime runs, the scheduler leaves autonomous specialist schedules and
triggers pending instead of claiming them. An exact task.create emitted from
Realtime may delegate a real peer Task to another Agent and carries immutable
creator provenance as the only exception. Causal ordering never makes that peer
a subtask. Turning Realtime off releases the pause without rewriting pending
Tasks. Session promotion is issued only after that release and waits until any
other running Task has finished.

The microphone remains live while Pocket speaks, so a fresh acoustic turn can
cancel playback and the in-flight Task generation without waiting for output to
finish. NeMo may classify a short backchannel without interrupting. These are
speech-transport decisions, never Task, Tool, or Knowledge decisions.
