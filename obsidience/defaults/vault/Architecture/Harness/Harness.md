---
type: knowledge
title: Harness
sources:
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/execution/scheduler.py
- resource: obsidience/harness/knowledge/dependencies.py
---

The Harness is Obsidience's Python runtime in `obsidience/harness/`. The API
lifetime owns the executor, scheduler, accepted-knowledge index, model runtime,
conversation lane and speech connection. These are subsystems of one Harness,
not independent Agents or Modules.

Accepted Agent Skill bindings or Task/Runbook bindings establish Tool authority;
retrieval supplies context. The executor binds the current objective, leases the
execution owner's selected model, validates each Tool call and records its outcome. The
[Shell](/Architecture/Shell/Shell.md) supplies desktop observations and implements explicit
window effects through its existing command boundary.

## Implementation map

- [Golden ontology](/Architecture/Harness/action-ontology.md): Article meanings and authority boundaries.
- [Local-first architecture](/Architecture/Harness/local-first-architecture--7d8e77cc.md): ownership of files, runtime state and interfaces.
- [LLM-wiki knowledge pattern](/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md): Source, accepted Markdown, indexing and publication.
- [Task activation](/Architecture/Harness/task-activation--b30a4642.md): work admission, dependencies, receipts and completion.
- [Activation packet protocol](/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md): bounded Knowledge and the Thinking Packet.
- [Executive model selection](/Architecture/Harness/current-executive-model--3745813a.md): Task model choice and device leases.
- [Memory and knowledge lifecycle](/Architecture/Harness/observations.md): native conversation context, native Hindsight memory, and reviewed durable Knowledge.
- [Real-time Executive](/Architecture/Harness/real-time-executive.md): speech feeding the same conversation and Task executor as Chat.
- [Research requests](/Architecture/Harness/research-requests--7bf0113c.md): Darwin Question/Learn and Heimdall Model ownership.

The whole project follows [Cordis composition](/Architecture/Harness/cordis-composition.md): explicit service dependencies, one lifecycle owner, and cleanup paired with acquisition. Chat and speech enter the [Executive Agent](/Agents/Executive/Executive.md) session and native DeepSeek loop. The Executive identity carries its standing instructions; DeepSeek owns the native model/Tool loop while the shared capability owner validates operations and receipts. Tool and Skill Article bodies are explanatory context, loaded when needed.
