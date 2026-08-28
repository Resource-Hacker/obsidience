---
assignee: '[[Agents/Executive/Executive]]'
kind: task
last_run: realtime-bf0459e94276
model: obsidience-gemma
reasoning_effort: none
runbook: '[[Runbooks/realtime]]'
status: completed
status_updated: '2026-08-27T14:23:45'
summary: Realtime was disabled by the owner.
taxonomy_path: executive/realtime
title: Realtime
---

Maintain one responsive, interruptible Executive conversation from the moment
the owner enables Realtime until the owner disables it or the runtime fails.

Realtime is the Task for the whole live session. Tool calls are steps within
this Task and do not create a Task per call. The Executive may explicitly
delegate a separate peer Task with `task.create`; that exact delegation is the
only specialist work admitted while autonomous specialist scheduling is
paused.

Success means the fixed speech transport is ready, each final utterance is
executed through this Task's selected model and activation packet, playback is
interruptible, and shutdown closes the Task cleanly. The speech runtime never
becomes a second reasoning, verifier, planner, Tool owner, or Agent.
