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
- **Runbook** gives reusable ordered or branching operating instructions.
  Task-bound procedures declare an exact Task and Agent. Reference-only
  Operations procedures declare their Agent and required Skills without
  inventing a Task or granting capabilities.
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
uses its own name, such as `Projects/Projects.md`; it is the index by
having children, not by acquiring another type. `index.md` and `log.md` are
reserved upstream navigation/history documents, not concept Articles.

Write body links as standard Markdown links to exact Article files, for example
`[Golden ontology](/Architecture/Harness/action-ontology.md)`.
Relative links are valid too. Root `status` describes document lifecycle only;
Task activity, pending inputs, and results stay in SQLite. Imported `verified`
assertions and source links never grant review approval or Tool authority.
OKF supplies the portable document contract, not another agent runtime.

## Ownership and execution identity

The Library holds every accepted Article for the owner. Each separate orbiting
Agent checks out shared Knowledge by exact Article identity and owns a scoped
Hindsight historical memory bank. Search, reads, graph expansion and displayed
membership use the same Knowledge scope. Historical memory from another Agent is
private; an explicitly handed-off Source supplies evidence without granting access.
Shared architecture describes the Obsidience environment; its placement does not
change the Guardian's definition-maintenance responsibility.
Reader role icons manage checkouts, not copies. Task assignment supplies its procedure closure. The Executive's direct Skills
supply the native Tool catalog for its conversation loop. Knowledge
checkout and model output cannot create a Tool grant.

Task is a reusable outcome definition. Activation is one requested occurrence;
Run is one attempt; Tool receipts establish dispatch and delivery evidence.
These runtime identities remain in the same SQLite ledger, not new Article types.
A Task status is a view over occurrences, not permission to replay a failed effect.
Conversation runs use the same receipts and activation ledger with the Agent ref
as their owner. Legacy SQLite fields named task_ref retain that exact owner ref;
they do not imply that an Agent is a Task Article.

## Cordis principles

Every Obsidience component follows Cordis's composition principles, whatever
runtime or framework hosts it ([A Programming Paradigm for Spatiotemporal
Composability](https://arxiv.org/abs/2608.25512); adopted 2026-09-12, made
runtime-independent 2026-10-09). Plugins, services and frameworks are
implementation roles: they are never Article types and never grant Tools.

1. **Contracts.** A component provides or consumes named service contracts and
   declares its required dependencies and optional integrations. Consumers
   depend on the contract, never on another owner's private state.
2. **Cleanup with acquisition.** Every subscription, listener, timer, worker,
   client and lease has one lifecycle owner that registers its cleanup when it
   acquires the resource.
3. **Availability.** Work runs only while its required dependencies are
   available. Cancellation, dependency loss or teardown stops and drains owned
   work; reconnection reuses the same owner and generation checks.
4. **One authority.** Each durable store, conversation, scheduler, model
   reservation and desktop input path has one owner. Others delegate through its
   interface instead of building a parallel path.
5. **Reversible composition, irreversible world.** Reloading or removing a
   component never undoes a delivered effect. Keep receipts and uncertain-outcome
   handling; never replay an uncertain effect.
6. **Short foreground path.** Keep the live path lean and measure real
   end-to-end boundaries before claiming a latency gain.
7. **Best available components.** Adopt a maintained framework or upstream
   component when it makes the system better: one per concern, through its
   supported extension points, pinned and recorded with its license in
   `artifacts.lock.json`. Never add a duplicate owner to bypass an unavailable
   dependency; migrate in stages behind a switch with a rollback until verified.

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

- `governs` [Task activation](/Architecture/Harness/task-activation--b30a4642.md) — Activation preserves the difference between outcome, procedure, guidance, capability, and execution.
- `governs` [Activation packet protocol](/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — Packet sections retain those semantic roles instead of flattening them into prompt text.
- `governs` [Real-time Executive](/Architecture/Harness/real-time-executive.md) — The speech connection delivers final transcripts to the Agent-owned session and native DeepSeek loop. It creates no Executive Task.
- `related_to` [LLM-wiki knowledge pattern](/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — The recursive Article hierarchy is the readable graph representation of this ontology.
- `governs` [Memory and knowledge lifecycle](/Architecture/Harness/observations.md) — DeepSeek owns native conversation compaction; Hindsight owns scoped historical memory. Curate and Link propose durable wiki recommendations through Review.

- `governs` [Cordis composition](/Architecture/Harness/cordis-composition.md) — Plugins provide explicit service contracts and own their lifecycle effects; they never become Article kinds or independent Tool grants.
- `governs` [Executive model selection](/Architecture/Harness/current-executive-model--3745813a.md) — Model and reasoning effort stay execution-owner concerns, so the DeepSeek model/Tool loop and completion authority are governed by this ontology's ownership rule rather than becoming separate Articles or routing authorities.
