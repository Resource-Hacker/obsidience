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
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

Obsidience classifies an object by what it does, never by its filename, folder,
screen label, or package format. Every knowledge-graph node is an Article, and
an Article with descendants is their readable index and condensation.

## Article types

- **Knowledge** states useful context. It is the default Article type.
- **Agent** names one accountable executor. Each named Agent has one Brain
  Article whose Tasks are its sole manual work assignments. Applicable accepted
  Runbooks derive each Task's Skill and Tool dependencies; the Agent does not
  carry independent Tool, Skill, or Runbook grants.
- **Task** states a reusable outcome and its acceptance condition.
- **Runbook** gives the reusable ordered procedure for a Task.
- **Tool** declares one executable interface to a real Source-backed
  Capability.
- **Skill** explains specifically how to use exactly one Tool.

Source is the real file or immutable evidence layer. Capability is executable
code behind a Tool. Module is a physical Obsidience product component such as
Shell or Harness. Source, Capability, Module, event, activation, and execution
are not additional Article types.

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
Reader role icons manage checkouts, not copies. Task assignment still supplies
the exact capability closure and Knowledge checkout cannot create a Tool grant.

Task is a reusable outcome definition. Activation is one requested occurrence;
Run is one attempt; Tool receipts establish dispatch and delivery evidence.
These runtime identities remain in the same SQLite ledger, not new Article types.
A Task status is a view over occurrences, not permission to replay a failed effect.

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
- `governs` [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md) — The speech button and connection are not a Task; each final transcript selects an exact accepted work Task, preserving the activation/execution boundary.
- `related_to` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md) — The recursive Article hierarchy is the readable graph representation of this ontology.
- `governs` [Observation lifecycle](/Agents/Executive/Architecture/Harness/observations.md) — Immediate, Temporary and Durable describe retention within the Article hierarchy; executable transitions remain the Compact and Promote Tasks rather than new Article kinds or memory authorities.
