---
type: knowledge
title: Activation packet protocol
sources:
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/knowledge/retrieval.py
- resource: obsidience/harness/models/llm.py
obsidience:
  approved_at: '2026-09-10T23:49:22.333585+00:00'
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
---

The Thinking Packet is the one model-facing activation packet used for live
text, live voice, manual Tasks, schedules, and event triggers. It gives a small
local model the smallest complete set of Articles and runtime bindings needed
for one outcome. Graph activity publishes the same Objective and Article refs
that the model receives.

The harness first selects one exact accepted Task. That Task's authored edges
resolve the assignee, Runbook, Skills, and Tools under
[Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md).
Similarity may supply Knowledge but cannot replace or broaden authority.

## Visible packet order

1. Agent Brain Article.
2. Exact Task Article and acceptance conditions.
3. Immutable runtime Objective for this activation.
4. Authorized Tool Articles.
5. Exact paired Skill Articles.
6. Applicable Runbook Articles.
7. Typed bindings and exclusions that are not the Objective or controller
   provenance.
8. Up to five relevant accepted Knowledge Articles.
9. For the active Executive conversation only, the single
   [Current conversation](/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md)
   Article.

The Objective is runtime data, not an Article kind. A bound owner request is
preserved as the complete Objective; without one, the deterministic fallback is
the Task title followed by its ordered Runbook titles. The same Objective drives
retrieval, graph activity, the provider request, and the execution ledger.

Immediate Observations is transient and unverified, has retrieval disabled, and
grants no Task, Tool, or durable Knowledge authority. It contains the newest
cumulative Temporary Observation summary followed by exact completed public
conversation pairs after that summary's boundary. The current Objective is not
duplicated into Immediate Observations before execution.

The Knowledge lane uses lexical and vector search with weighted reciprocal-rank
fusion, preserves three direct hits when available, and admits at most two
directly linked Knowledge neighbors within a 1,200-estimated-token allowance.
It performs no generative expansion, cross-encoder pass, or elapsed-time cutoff.
The current packer uses at most the first 1,200 body characters of each nominated
Article and can include fewer than five Articles when the estimated budget is
exhausted. These are explicitly excerpts, not full-document retrieval.
Retrieval failure may remove optional context but can never invent authority,
procedure, a Tool, or a success claim. Immediate Observations is attached by
exact identity rather than search.

The existing Action Trace exposes bounded Knowledge selection accounting
inside the Thinking Packet's Relevant Knowledge section. It identifies eligible
search hits and examined direct-seed neighbors as supplied, excerpted, or
omitted, with the selection reason and exact body character range where
available. These counts describe that nominated candidate set, not every
Article in the Vault. At most 32 entries are displayed, with omitted-entry
counts and explicit clipping. Per-chunk character-based token estimates are
selection diagnostics; they exclude joining separators and are separate from
the exact tokenizer count of the complete provider request. This projection
adds no provider instructions, authority, Article kind, or memory store.

A Tool Article is the graph-facing interface to a real Source-backed Capability.
A Skill teaches that Tool. Retrieval, execution, indexing, Source storage, review and speech transport are
subsystems of the Harness Module. They may support a Capability adapter, but
they do not become assignments or Task authority.

The provider representation retains the same semantic sections but does not
serialize the visible order as one undifferentiated message. Stable identity,
Task and capability/procedure sections form provider-system context; the
Objective, current Bindings and retrieved Knowledge form provider-user context,
with conversation context carried separately. Compiler-owned section boundaries
prevent Article prose from promoting itself into runtime instructions.

Before inference, the selected model's tokenizer counts the actual provider
request; an oversized request fails with required and available token counts
rather than silently truncating the Objective. The execution ledger records the
exact Objective, Task, Runbook hash, reasoning effort, calls, evidence, and
terminal result.

## Relationships

- `implements` [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md) — Each packet section preserves one canonical semantic role.
- `implements` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — Bounded hybrid retrieval supplies the relevant Knowledge lane.
- `depends_on` [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) — Exact Task edges establish the packet's executable authority.
- `implements` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — The packet's bounded context, exact paired Tool/Skill edges, and pre-inference sizing operationalize the local-first model and authority contracts.
- `depends_on` [Executive model selection](/Agents/Executive/Architecture/Harness/current-executive-model--3745813a.md) — The pre-inference token gate uses the Task-selected model and reasoning effort defined by that selection policy.
