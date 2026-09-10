---
type: knowledge
title: Harness
sources:
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/execution/scheduler.py
- resource: obsidience/harness/knowledge/dependencies.py
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

The Harness is Obsidience's Python runtime in `obsidience/harness/`. The API
lifetime owns the executor, scheduler, accepted-knowledge index, model runtime,
conversation lane and speech connection. These are subsystems of one Harness,
not independent Agents or Modules.

Accepted Task, Runbook, Skill and Tool edges establish authority; retrieval
supplies context. The executor binds the current objective, leases the
Task-selected model, validates each Tool call and records its outcome. The
[Shell](/Agents/Executive/Architecture/Shell/Shell.md) supplies desktop observations and implements explicit
window effects through its existing command boundary.

## Implementation map

- [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md): Article meanings and authority boundaries.
- [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md): ownership of files, runtime state and interfaces.
- [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md): Source, accepted Markdown, indexing and publication.
- [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md): work admission, dependencies, receipts and completion.
- [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md): bounded Knowledge and the Thinking Packet.
- [Executive model selection](/Agents/Executive/Architecture/Harness/current-executive-model--3745813a.md): Task model choice and device leases.
- [Observation lifecycle](/Agents/Executive/Architecture/Harness/observations.md): Immediate, Temporary and durable Knowledge.
- [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md): speech feeding the same conversation and Task executor as Chat.
- [Research requests](/Agents/Executive/Architecture/Harness/research-requests--7bf0113c.md): Question, Learn, Feed Distill and Model outcomes.
