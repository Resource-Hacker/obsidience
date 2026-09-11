---
type: knowledge
title: Real-time Executive
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/harness/realtime/runtime.py
- resource: obsidience/harness/realtime/media.py
- resource: obsidience/harness/realtime/speech/worker.py
- resource: obsidience/harness/conversation/runtime.py
- resource: obsidience/harness/conversation/selection.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/execution/scheduler.py
obsidience:
  approved_at: '2026-09-10T23:49:22.333585+00:00'
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
---

Realtime is the speech connection and session infrastructure controlled by the
interface button. It keeps audio available between requests. The work itself
uses the same [Query](/Tasks/query.md) and
[Computer Use](/Tasks/executive/operate.md) definitions as typed Chat. Each selected
Task owns its authored model, reasoning effort, Runbook, Tool authority, and
acceptance condition; the connection has no Task or Runbook of its own.

Pipecat's upstream `LocalAudioTransport` opens the microphone and speaker selected
in Settings > AI & Voice through process-scoped Pulse routing. NVIDIA NeMo owns streaming
turn boundaries, Nemotron Speech Streaming EN 0.6B produces transcripts on the
RTX 4080, and Pocket TTS produces speech on CPU. These fixed components only
transport the turn. Obsidience adds no browser audio client, audio WebSocket, or
second capture/playback lane.

At start, Realtime freezes the selected microphone, speaker, and Pocket voice,
wakes the OBSBOT camera through its official SDK, and disables the camera's
120-second no-video sleep timer. At stop, it restores that timer and sleeps the
camera. The camera's physical state owns its microphone state.

The bounded selector sees the current request in a separate final message, not
as another field inside historical context. It classifies one coherent
outcome/application/scope combination; the controller derives the exact assigned
Task and rereads its accepted definition. Polite execution requests are distinct
from explanations, quotations, withdrawals, and bare corrections. The response
grammar prevents impossible field combinations but does not prove semantic intent.

Each final transcript selects an exact work Task and executes through the one
activation compiler, model lease, Tool path, ledger, and graph activity.
`task.complete` records the ordinary terminal result; its public summary is
the same answer delivered to Chat or spoken by Pocket. The visible Thinking
Packet and its exact refs are the graph animation source. Speech onset may
cancel Pocket playback and the current execution without closing the
microphone; NeMo may ignore a backchannel without gaining semantic authority.

Typed Chat and Realtime share one exact SQLite-backed Executive conversation.
Completed public turns project through the real
[Current conversation](/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md)
Article beneath Immediate Observations. The user turn is persisted before
execution; an assistant reply is committed only for a current completed result.
Canceled, failed, blocked, interrupted or stale model output is not committed as
a successful assistant reply, but its user's request is not erased. Conversation compaction
and promotion use their ordinary Tasks and never create a second memory path.

Idle listening is not a global pause. Actual foreground work, speech startup or
shutdown, and the existing physical GPU reservations control admission. The
scheduler never unloads speech simply to start an incompatible specialist model.
An Executive may delegate a Question or Learn through its authorized `task.create`;
controller provenance binds the actual caller and user turn. A completed sourced
finding can return before background wiki publication. Explicit publication
requests retain their separate acceptance condition.

An ordinary launch dispatches once and waits for the existing Shell scene to
witness readiness. A timeout is not permission to launch again. Query can request
one controlled pre-effect admission correction if an action was misrouted; it
cannot authorize a Tool or invent a target. An effect-free Query attempt to
delegate Computer Use is intercepted before Tool dispatch and requests the same
one-time recheck. It records an undispatched controller disposition, not a
fabricated task.complete. The recheck uses the original owner turn with bounded
feedback; attempted Tool arguments cannot select the target. Prior effects,
created Tasks, cancellation, or an earlier recheck prevent automatic replay.
Independent activations retain their
own identities, context and evidence while the speech connection stays ready.

## Relationships

- `implements` [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — Every final transcript uses the same packet and graph-activity path as other Tasks.
- `implements` [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) — Spoken and typed requests select the same accepted work Tasks and complete through one executor.
- `implements` [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md) — The speech connection stays a connection, not a Task, and each final transcript selects an exact work Task, per the ontology's rule that a UI verb becomes a Task only when it names an independently queueable outcome.
- `depends_on` [Executive model selection](/Agents/Executive/Architecture/Harness/current-executive-model--3745813a.md) — Each selected work Task supplies its model and reasoning effort.
- `depends_on` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — Realtime's final transcripts execute Tasks through the pattern's bounded Thinking Packet and exact accepted-graph capability spine.
- `related_to` [Hyprland shell scene](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md) — Current focused and unfocused panes enter only as bounded runtime bindings.
- `related_to` [Research requests](/Agents/Executive/Architecture/Harness/research-requests--7bf0113c.md) — Delegation from an interactive Realtime execution follows the Research delegation path to [Darwin](/Agents/Darwin/Darwin.md).
- `implements` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — Spoken requests use the same Task executor, model lease and SQLite conversation as typed Chat; the speech connection adds no independent reasoning or memory owner.
- `related_to` [Executive](/Agents/Executive/Executive.md) — The Realtime connection is the Executive's speech interface; each final transcript executes through that same accountable Executive as typed Chat.
