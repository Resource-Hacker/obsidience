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
- resource: obsidience/harness/capabilities/task/complete.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/execution/scheduler.py
---


Chat owns the Wake word, Realtime and Mute controls, Executive readiness and
live recognition. Wake word is the default: the existing STT listens for Computer,
then only the following command text enters the command buffer, Chat or the
Executive. Unaddressed speech never interrupts or enters conversation. A trigger
without a command allows an eight-second pause. The gate closes after the final
command; Realtime instead keeps continuous conversation available without the
name. Mute closes the microphone. Mode changes cancel the current turn and reject
old-revision speech events. Both modes share the same worker and conversation.

Voice reply-format instructions follow the shared prompt and native Tool schemas,
so typed Chat and speech reuse the same cached instruction prefix without
changing their respective response formats.

Idle model-work boundaries notify the existing Conversation owner to prepare the
selected Executive conversation and native Tool schemas. Standby may restore its
configured model only on idle hardware; one discarded token warms the real prompt.
Readiness becomes warm only after that preparation succeeds. Real model work
preempts and drains it. No Agent run, Tool effect, conversation write, Observation
materialization or polling loop is created by standby.

Arming Wake word during active model work waits for its release without requesting a foreground interruption.

Wake mode's existing STT hardware reservation is yieldable: conflicting model work
drains the speech worker and releases its device before activation, then the last
work-release edge restores listening and Executive preparation. At most one already
accepted public reply may wait for restoration; its cancellation generation must
still match. STOP and new input clear it. Realtime retains its hard reservation.
The same-login intent records wake, realtime or off; missing intent defaults to
wake, while explicit Mute persists across Harness restarts in that login.


Realtime is the speech connection and session infrastructure controlled in Chat. It keeps audio available between requests. Every Chat request and final speech transcript enters the same Executive conversation and ADK loop. The Agent carries standing identity instructions, direct Skills, model and reasoning effort; ADK sequences native Tool calls the model selects directly from the accepted schemas; the compiler supplies context and retrieved Knowledge. The audio connection has no Task or Runbook of its own.

ADK owns the active conversation log and its provider window; Hindsight owns historical observations and scoped recall.

Pipecat's upstream `LocalAudioTransport` opens the microphone and speaker selected
in Settings > AI & Voice through process-scoped Pulse routing. NVIDIA NeMo owns streaming
turn boundaries, Nemotron Speech Streaming EN 0.6B produces transcripts on the
configured speech device, and Pocket TTS produces speech on CPU. These fixed components only
transport the turn. Obsidience adds no browser audio client, audio WebSocket, or
second capture/playback lane.

The first partial transcript prepares the canonical Executive prompt and native
Tool schemas after its exact NeMo interruption drains previous work. The shared
model owner admits one cancellable warmup only on idle resident llama.cpp;
new partials replace pending text. One generated token is explicitly discarded
because the installed build also generates one when zero is requested. This
preparation starts no Agent run, dispatches no Tools, writes no conversation or
Articles. Context projection is read-only, including
retention selection. Final speech, Chat and STOP cancel it; ordinary model
leases preempt it. Final admission recompiles the complete corrected request
and fresh state, and only exact provider prompt prefixes can be reused.

NeMo's partial words carry the worker's exact speech sequence; they are not
irrevocably locked instructions. The normal 700 ms pause allowance remains.
An ASR word-update gap cannot end an utterance while VAD still detects speech;
the transcript-idle fallback applies only to late text without voiced activity.

Pocket synthesis remains serialized on its shared model. Cancellation stops the
native latent producer cooperatively through a temporary PyTorch hook, discards
cancelled PCM and drains Pocket's ordinary error/sentinel/decoder-join cleanup.
The hook is removed before the next synthesis. The non-daemon synthesis owner
cannot leave native inference running during interpreter shutdown. Early stream
closure must not abandon those workers or allow overlapping model calls.

At start, Realtime freezes the locally selected microphone, speaker and voice. Optional device lifecycle adapters own any required wake and sleep operations.

Admission validates the accepted Executive identity and exact persisted user turn. The ADK loop exposes the native capabilities granted by direct Skills. The Executive model receives the current Objective, full bounded conversation, current semantic Scene and historical receipts, then chooses the next Tool directly. A target-only correction continues the preceding question and never authorizes an effect by itself. Current visible questions use computer.observe; launch, focus, placement and input require the corresponding requested operation and current Tool evidence.
The Agent-owned run uses the shared activation compiler, model lease, Tool path, ledger and graph activity. There is no Query/Computer Use classification or reclassification pass.
Ordinary native text passes the shared completion authority locally, then the accepted
answer is committed and delivered to Chat or Pocket. Structured task.complete remains
available for terminal status and computer-state verification. The visible Thinking
Packet and its exact refs are the graph animation source. Speech onset may
cancel Pocket playback and the current execution without closing the
microphone; NeMo may ignore a backchannel without gaining semantic authority.


Idle listening is not a global pause. Actual foreground work, speech startup or
shutdown, and the existing physical GPU reservations control admission. The
scheduler retains hard reservations in Realtime; Wake mode can yield through the existing model owner.
An Executive may delegate a Question or Learn through its authorized `task.create`;
controller provenance binds the actual caller and user turn. A completed sourced
finding can return before background wiki publication. Explicit publication
requests retain their separate acceptance condition.

An ordinary launch dispatches once and waits for the existing Shell scene to
witness readiness. The exact managed launch ending before a ready window is a failure; a
timeout leaves readiness and loading unverified. Neither authorizes another
launch. Accepted failed public replies retain bounded, exact-run Tool evidence
for follow-up explanation without becoming successful conversation pairs. The Executive uses this history in its Agent-owned response. It does not run a classification recheck or reissue uncertain effects.

## Relationships

- `implements` [Activation packet protocol](/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — Every final transcript uses the same compiler, executor and graph-activity path as Task execution.
- `implements` [Task activation](/Architecture/Harness/task-activation--b30a4642.md) — Spoken and typed requests enter the same Agent-owned conversation, ADK loop and capability core.
- `implements` [Golden ontology](/Architecture/Harness/action-ontology.md) — The speech connection delivers final transcripts to the Executive identity; only independently queueable outcomes require Tasks.
- `depends_on` [Executive model selection](/Architecture/Harness/current-executive-model--3745813a.md) — The Executive identity supplies conversation model and reasoning settings; specialist Tasks retain their own selections.
- `depends_on` [LLM-wiki knowledge pattern](/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — Realtime's final transcripts use bounded Thinking Packets and exact Agent Skill/Tool bindings.
- `related_to` [Hyprland shell scene](/Architecture/Shell/hyprland-shell-scene.md) — Current focused and unfocused panes enter only as bounded runtime bindings.
- `related_to` [Research requests](/Architecture/Harness/research-requests--7bf0113c.md) — Delegation from an interactive Realtime execution follows the Research delegation path to [Darwin](/Agents/Darwin/Darwin.md).
- `implements` [Local-first architecture](/Architecture/Harness/local-first-architecture--7d8e77cc.md) — Spoken requests use the same executor, model lease and native conversation as typed Chat; the speech connection adds no independent reasoning or memory owner.
- `related_to` [Executive](/Agents/Executive/Executive.md) — The Realtime connection is the Executive's speech interface; each final transcript executes through that same accountable Executive as typed Chat.

The [Cordis composition](/Architecture/Harness/cordis-composition.md) design governs these dependencies and lifetimes. UI preparation feedback follows the exact accepted turn immediately; actual Article highlights still follow only compiled packet/Tool refs. The existing speech endpoint and accepted-completion speech boundary retain ownership.
