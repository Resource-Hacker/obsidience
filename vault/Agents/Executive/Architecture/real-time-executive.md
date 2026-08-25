---
approved_at: '2026-08-25T15:39:34'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Real-time Executive
---

The real-time Executive is one Obsidience execution surface, not another
Agent, harness, scheduler, memory store, or Tool authority. It uses two local
models because conversation and planning have different timing requirements:

- Gemma 4 E2B Duplex receives the live stream, owns interruption timing, and
  is the only model allowed to publish the Executive's spoken response.
- DiffusionGemma 26B-A4B privately plans a response from the exact activation
  packet. Its output is advisory until the duplex receiver accepts it for the
  current, non-cancelled generation.

Every completed utterance enters the same Task selector and activation
compiler used by text, manual, scheduled, and event-triggered work. The packet
order is Agent Identity, Task, Tools, Skills, Runbook, and up to five Relevant
Knowledge Articles. The graph therefore shows the exact Articles that are
active while the Executive thinks and speaks, and the completed turn returns
through the ordinary bounded Temporary Observations path. The packet's
construction rules are specified by
[[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]].

Obsidience alone selects Tasks, retrieves Knowledge, authorizes and invokes
Tools, records evidence, and decides whether an outcome succeeded. Neither
model may invent a capability, execute an unbound Tool, persist memory, or
claim an external effect without the normal Task executor and verification.

The microphone transcript remains mutable until endpointing, so private
planner overlap is disabled in the production path. Loopback activation
requests run on a sidecar thread with a fresh bounded HTTP connection; they
never block the receiver's 80 ms interruption loop.
