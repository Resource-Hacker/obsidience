---
type: knowledge
title: Voice interaction
---

Voice is the owner's preferred live interface. Prioritize low latency, visible
partial and final transcription, prompt speech, and natural interruption. Spoken
answers should normally be one or two useful sentences unless detail is requested.
Do not routinely restate the request, narrate Tool calls, speak reasoning or errors,
or add acknowledgement filler. Claim success only after verification.

The fixed “Realtime active.” startup confirmation is intentional. During a
conversation, interruption cancels pending generation and playback while the
microphone remains available for barge-in. Chat shows the same final transcript
and completed public reply that the Executive received and produced.

- [Realtime Executive](/Agents/Executive/Architecture/real-time-executive.md)
  separates the fixed speech transport from Task-selected reasoning.
- [Observation lifecycle](/Agents/Executive/Architecture/observations.md) explains
  how spoken and typed turns share the current conversation.
