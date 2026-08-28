---
approved_at: '2026-08-27T18:10:12'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
title: Activation packet protocol
---

An activation packet gives a small local model the smallest complete set of
Articles and runtime bindings needed for one outcome. The same executor compiles
it for live text, live voice, manual Tasks, scheduled Tasks, and event-triggered
Tasks. The visible packet is the Thinking Packet; graph activity publishes the
exact Article refs and Objective the model received.

Fast search may nominate a Task candidate, but the harness must select one exact
accepted Task. Its authored links then resolve assignee, Runbook, Skills, and
Tools; similarity cannot replace or broaden authority. The Knowledge lane
combines lexical and vector search with weighted reciprocal-rank fusion, keeps
three direct hits when available, and admits at most two directly linked
neighbors. It has no generative expansion, cross-encoder pass, or elapsed-time
deadline.

## Packing order

1. Agent Identity Article.
2. Exact Task Article and acceptance conditions.
3. Immutable runtime Objective for this activation.
4. Authorized Tool Articles.
5. Exact paired Skill Articles.
6. Applicable Runbook Articles.
7. Typed bindings and exclusions that are not the Objective or controller
   provenance.
8. Up to five relevant accepted Knowledge Articles, including bounded direct
   graph neighbors.
9. For the active Executive conversation only, the single
   [[Agents/Executive/Observations/immediate-observations|Immediate Observations]]
   Article.

The Objective is runtime data, not an Article kind. When an owner request is
bound, its exact admitted text is the Objective. Without a request, the
deterministic fallback is the selected Task title followed by its ordered
Runbook titles. That one value drives retrieval, graph activity, the provider
packet, and the run ledger. Request, source, event, and response-contract
controller data are not duplicated into Bindings.

Immediate Observations is transient and unverified, has retrieval disabled, and
grants no Task, Tool, or durable Knowledge authority. It contains the newest
cumulative Temporary Observation summary followed by exact completed public
conversation pairs after that summary's boundary. The current Objective is not
duplicated into Immediate Observations before execution.

Every activation uses a 1,200-estimated-token Knowledge allowance. Every section
keeps its semantic label. Retrieval failure may remove optional background
Knowledge, but it can never invent authority, procedure, a Tool, or a success
claim. Immediate Observations is attached by exact identity rather than search.

A Tool Article is the graph-facing interface to a real Source-backed Capability.
A Skill teaches that Tool. Internal Obsidience Modules such as retrieval,
execution, scheduling, indexing, Source storage, review, and speech transport
may support the runtime or a Capability adapter, but they never enter the
Thinking Packet as checkout or Task authority.

The execution ledger records the exact Objective, Task, Runbook hash, reasoning
effort, calls, evidence, and terminal result. Historical runs created before
Objective binding remain honest empty values rather than fabricated backfills.
