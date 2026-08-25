---
approved_at: '2026-08-25T07:07:48'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Local-first architecture
---

Obsidience is a standalone local harness with one authority for each concern.
The accepted Markdown vault is the durable knowledge graph. Source is immutable
blob storage. The run ledger owns operational history. One interpreter owns
Task activation, retrieval, Tool authorization, execution, scheduling, review,
and the operator API; the UI is a projection of those services.

The primary target is a low-parameter model on consumer hardware. Contracts
therefore favor small bounded contexts, closed Tool sets, stable names, exact
edges, explicit acceptance conditions, and deterministic validators. A larger
or remote model may be configured, but the architecture must never depend on
its broad latent knowledge.

Presentation, Library checkout, Tasks, agent identities, and voice do not create
duplicate model loops, memory stores, schedulers, or mutation paths. A capability
becomes active only when a real Tool binding and its paired Skill validate.

## Relationships

- `related_to` [[Agents/Executive/Executive|Executive]] - Executive is the user-facing role of the local runtime.
- `implements` [[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]] - Bounded activation makes local small-model execution practical.
- `implements` [[Agents/Executive/Architecture/task-activation--b30a4642|Task activation]] - Task activation is where the architecture's exact-edge contract is realized: a capability is active only when its Tool binding and paired Skill resolve and validate.
- `implements` [[Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a|LLM-wiki knowledge pattern]] - The accepted Markdown vault, immutable Source, exact-edge capability activation, and low-parameter local target realize the wiki's maintenance and retrieval pattern.
