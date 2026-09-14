---
type: knowledge
title: Golden ontology
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/harness/knowledge/format.py
- resource: obsidience/harness/knowledge/dependencies.py
- resource: obsidience/harness/capabilities/registry.py
- resource: DESIGN.md
---

# Golden ontology

Obsidience classifies an object by what it does, never by its filename, folder,
screen label, or package format. Every knowledge-graph node is an Article, and
an Article with descendants is their readable index and condensation.

## Article types

- **Knowledge** states useful context. It is the default Article type.
- **Agent** names one accountable executor. Each named Agent has one Brain
  Article. Assigned Tasks are independently queueable work. A conversational Agent
  carries its standing instructions in its identity and declares its available
  Skills directly. Each Skill binds one Tool. Native capability schemas are
  available to the DeepSeek Executive loop; an Executive Task or Runbook hub is unnecessary.
- **Task** states a reusable outcome and its acceptance condition.
- **Runbook** gives reusable ordered or branching instructions for a Task.
  An Agent's standing instructions belong to its identity Article.
- **Tool** describes one registered executable interface to a real
  Source-backed Capability. Its schema and execution live in code.
- **Skill** explains specifically how to use exactly one Tool.

Source is the real file or immutable evidence layer. Capability is executable
code behind a Tool. Module is a physical Obsidience product component such as
Shell or Harness. Source, Capability, Module, plugin, service, event, activation, and execution
are not additional Article types.

## Executable contracts and explanatory Articles

The owner accepts DeepSeek's native Tool schema and invocation protocol for the
Executive-loop migration. The code-owned Tool definition is the executable
contract: name, parameters, output and implementation. Tool and Skill Articles
explain the registered capability and its use; they do not impose a second
machine-call schema or require Obsidience's existing `{tool, args}` response
format. Keep exact Article-to-Capability provenance and accepted Agent bindings,
while changing adapters and documentation together when the executable interface
changes. Ordinary conversational text can use the upstream response stream;
capability code retains argument validation, receipts, target verification and
cancellation. DeepSeek now owns the Executive model/Tool loop. The existing
completion authority validates ordinary final text locally; native task.complete
remains available for structured terminal status and computer-state verification.

## Document format

Each Article is one native Open Knowledge Format Markdown file. Its required
`type` declares one of the six meanings above. Common document fields stay at
the root; Obsidience bindings, triggers, and permission metadata live under
`obsidience`. Skills remain exactly one-to-one with Tools. A parent's Article
uses its own name, such as `Observations/Observations.md`; it is the index by
having children, not by acquiring another type. `index.md` and `log.md` are
reserved upstream navigation/history documents, not concept Articles.

Write body links as standard Markdown links to exact Article files, for example
`[Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md)`.
Relative links are valid too. Root `status` describes document lifecycle only;
Task activity, pending inputs, and results stay in SQLite. Imported `verified`
assertions and source links never grant review approval or Tool authority.
OKF supplies the portable document contract, not another agent runtime.

## Ownership and execution identity

The Library holds every accepted Article for the owner. Each separate orbiting
Agent owns its local Knowledge and Observations and checks out selected shared
Knowledge by exact Article identity. Search, reads, graph expansion and displayed
membership use the same scope. Observations from another Agent are private;
an explicitly handed-off Source supplies evidence without granting graph access.
Reader role icons manage checkouts, not copies. Task assignment supplies its procedure closure. The Executive's direct Skills
supply the catalog from which routing selects each conversation packet. Knowledge
checkout and model output cannot create a Tool grant.

Task is a reusable outcome definition. Activation is one requested occurrence;
Run is one attempt; Tool receipts establish dispatch and delivery evidence.
These runtime identities remain in the same SQLite ledger, not new Article types.
A Task status is a view over occurrences, not permission to replay a failed effect.
Conversation runs use the same receipts and activation ledger with the Agent ref
as their owner. Legacy SQLite fields named task_ref retain that exact owner ref;
they do not imply that an Agent is a Task Article.

## Structural rules

Task hierarchy expresses reusable scope, not chronological order. Only an
explicit `subtasks` edge creates a child Task. A Task activated by another Task
remains its authored peer. Procedure, branching, retry, and tool order belong in
the Runbook. Runtime status and evidence belong to the execution ledger, not to
reusable definitions.

A UI verb becomes a Task only when it names an independently queueable outcome
with its own acceptance condition. Otherwise it remains a Runbook step or Tool
operation. Similarity may retrieve Knowledge, but only exact accepted graph
edges may select Agent, Task, Runbook, Skill, or Tool authority.

## Relationships

- `governs` [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) — Activation preserves the difference between outcome, procedure, guidance, capability, and execution.
- `governs` [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — Packet sections retain those semantic roles instead of flattening them into prompt text.
- `governs` [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md) — The speech connection delivers final transcripts to the Agent-owned session and native DeepSeek loop. It creates no Executive Task.
- `related_to` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — The recursive Article hierarchy is the readable graph representation of this ontology.
- `governs` [Observation lifecycle](/Agents/Executive/Architecture/Harness/observations.md) — Immediate, Temporary and Durable describe retention within the Article hierarchy; executable transitions remain the Compact and Promote Tasks rather than new Article kinds or memory authorities.

- `governs` [Cordis composition](/Agents/Executive/Architecture/Harness/cordis-composition.md) — Plugins provide explicit service contracts and own their lifecycle effects; they never become Article kinds or independent Tool grants.
- `governs` [Executive model selection](/Agents/Executive/Architecture/Harness/current-executive-model--3745813a.md) — Model and reasoning effort stay execution-owner concerns, so the DeepSeek model/Tool loop and completion authority are governed by this ontology's ownership rule rather than becoming separate Articles or routing authorities.
