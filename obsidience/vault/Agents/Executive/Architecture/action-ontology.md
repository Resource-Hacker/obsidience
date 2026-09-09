---
type: knowledge
title: Golden ontology
obsidience:
  provenance: proposed by Alexandria (task Tasks/link)
  approved_at: '2026-09-08T20:30:16'
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
`[Golden ontology](/Agents/Executive/Architecture/action-ontology.md)`.
Relative links are valid too. Root `status` describes document lifecycle only;
Task activity, pending inputs, and results stay in SQLite. Imported `verified`
assertions and source links never grant review approval or Tool authority.
OKF supplies the portable document contract, not another agent runtime.

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

- `governs` [Task activation](/Agents/Executive/Architecture/task-activation--b30a4642.md) — Activation preserves the difference between outcome, procedure, guidance, capability, and execution.
- `governs` [Activation packet protocol](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md) — Packet sections retain those semantic roles instead of flattening them into prompt text.
- `governs` [Real-time Executive](/Agents/Executive/Architecture/real-time-executive.md) — The speech button and connection are not a Task; each final transcript selects an exact accepted work Task, preserving the activation/execution boundary.
- `related_to` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a.md) — The recursive Article hierarchy is the readable graph representation of this ontology.
