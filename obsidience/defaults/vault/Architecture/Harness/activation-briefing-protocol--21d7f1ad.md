---
type: knowledge
title: Activation packet protocol
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/knowledge/retrieval.py
- resource: obsidience/harness/models/llm.py
---

The Thinking Packet is the one model-facing activation packet used for live
text, live voice, manual Tasks, schedules, and event triggers. It gives a small
local model the smallest complete set of Articles and runtime bindings needed
for one outcome. Graph activity publishes the same Objective and Article refs
that the model receives.

Chat and speech enter the Executive session directly. The compiler supplies the identity's standing Runtime instructions, bounded conversation, current bindings and relevant Knowledge. The DeepSeek loop receives native schemas from the accepted direct Skill/Tool catalog and chooses the next Tool. There is no preliminary model routing request. Explanatory Tool and Skill bodies can be read when needed; advertising their schemas alone does not add them to the packet's Article refs. Ordinary text is accepted through the same completion authority without a model-generated completion call.

Independently queueable Tasks still resolve their authored procedure under
[Task activation](/Architecture/Harness/task-activation--b30a4642.md).
Both paths share the compiler and operation/receipt owner; Tasks retain their procedure loop. Knowledge cannot broaden their authority.

## Compiled instructions

The selected Tool, paired Skill and Runbook contribute authored Runtime sections
and applicable operation sections. Complete reference text remains in Reader.
Task operation profiles only narrow their accepted capability catalog. The Executive uses native schemas with the complete code-owned argument contract validated before dispatch. Exact section
hashes and ranges are recorded with the packet. The decoder constrains Tool name,
argument types, required fields and allowed keys; adapters enforce bounds and
state-dependent acceptance. Finite nested string/array ceilings stay out of the
llama.cpp grammar because expanding them exceeds its rule-repetition limit.
They remain in canonical contracts and adapter checks, with output-token limits
bounding model generation.

The current Thinking Packet and execution receipts expose the exact objective,
selected context identities and controller evidence through existing runtime
surfaces. Executive conversation context stays in its DeepSeek session; current
conversation and activation are not Knowledge Articles. Actual read/search
results extend the runtime evidence. A displayed thinking path represents supplied
or read context, not hidden model reasoning. Proposed relationships become durable
only through ordinary publication. Checkout refresh is passive.

## Visible packet order

DeepSeek owns the active conversation and native compaction; Hindsight owns historical observations and scoped recall.

The Objective is runtime data, not an Article kind. A bound owner request is
preserved as the complete Objective; without one, the deterministic fallback is
the Task title followed by its ordered Runbook titles. The same Objective drives
retrieval, graph activity, the provider request, and the execution ledger.

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
exact Objective, execution owner, native capability catalog when applicable, instruction-owner hash,
reasoning effort, calls, evidence, and
terminal result.

## Relationships

- `implements` [Golden ontology](/Architecture/Harness/action-ontology.md) — Each packet section preserves one canonical semantic role.
- `implements` [LLM-wiki knowledge pattern](/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — Bounded hybrid retrieval supplies the relevant Knowledge lane.
- `depends_on` [Task activation](/Architecture/Harness/task-activation--b30a4642.md) — Exact Agent Skill bindings or Task/Runbook edges establish the packet's executable authority.
- `implements` [Local-first architecture](/Architecture/Harness/local-first-architecture--7d8e77cc.md) — The packet's bounded context, exact paired Tool/Skill edges, and pre-inference sizing operationalize the local-first model and authority contracts.
- `depends_on` [Executive model selection](/Architecture/Harness/current-executive-model--3745813a.md) — The pre-inference token gate uses the execution owner's selected model and reasoning effort defined by that selection policy.
