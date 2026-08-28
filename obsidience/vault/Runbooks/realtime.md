---
title: Realtime procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Executive/Executive]]'
task: '[[Tasks/executive/realtime]]'
skills:
- '[[Skills/activating-a-task]]'
- '[[Skills/benchmarking-a-model]]'
- '[[Skills/capturing-source-evidence]]'
- '[[Skills/checking-harness-status]]'
- '[[Skills/configuring-a-model]]'
- '[[Skills/observing-the-computer]]'
- '[[Skills/acting-on-the-computer]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/inspecting-a-model]]'
- '[[Skills/inspecting-maintenance-candidates]]'
- '[[Skills/launching-an-application]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/registering-model-source]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/searching-the-web]]'
- '[[Skills/validating-the-vault]]'
---

Keep one low-latency Executive session alive until the owner turns Realtime
off. The button owns Task completion; `task.complete` is not a conversational
Tool.

1. Reserve the RTX 4080 for the fixed speech runtime: Pipecat, NVIDIA NeMo
   streaming turn taking, and Nemotron Speech Streaming EN 0.6B at 160 ms.
   Open the microphone and speaker selected in Hardware with Pipecat's upstream
   `LocalAudioTransport` and process-scoped Pulse routing. When Realtime becomes
   ready, enable the OBSBOT SDK microphone-during-sleep switch; disable it when
   Realtime ends.
2. Keep that one Pipecat input open while Pocket speaks so speech onset can
   cancel Pocket TTS without closing the microphone. Backchannels may be ignored
   by NeMo without interrupting the current response. Do not create a second
   capture, playback, browser-audio, or audio-WebSocket lane.
3. Pass each final transcript to this ordinary Realtime Task. Compile the same
   Agent Identity, Task, Tools, Skills, Runbook, and retrieved Knowledge packet
   used by every other Task, then invoke only the model and reasoning effort
   selected on this Task.
4. Stream the selected model's public answer to Pocket TTS 3.0.2 on CPU with the
   voice selected in Hardware. The speech stack transports the answer; it never
   selects Tools, creates a Plan, reasons, or owns intent.
5. Mirror the Task activation, retrieval, model execution, Tool calls, and
   playback lifecycle into the graph. Do not create a second execution lane.
6. A Tool call remains a step of Realtime. Use `task.create` only when the
   owner or Executive explicitly delegates a real peer Task to another Agent.
   The created Task carries exact Realtime provenance; task ordering does not
   imply hierarchy.
7. While Realtime runs, autonomous scheduled and triggered specialist Tasks
   remain pending. Ending Realtime releases the pause without rewriting them.

Keep the microphone live while the selected model speaks. On interruption,
cancel pending public output and reject late generations. Keep graph and Tool
work outside the receiver loop.
