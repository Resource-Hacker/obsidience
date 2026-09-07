---
type: knowledge
title: Task activation
obsidience:
  approved_at: '2026-09-07T13:50:54'
  provenance: proposed by Alexandria (task Tasks/link)
---

Obsidience has one reusable Task Article and several ways to activate it: manual
invocation, voice, typed input, a graph or shell event, a schedule, or an exact
peer `task.create`. Runtime state belongs to the execution ledger and Tasks
pane, not to another object type.

The Tasks pane is a filtered operational matrix. It shows only Tasks with a
schedule, event trigger, or active execution. It is not the Task repository; the
shared Task hierarchy lives in Library.

A selected parent includes its descendant Task scope unless an exact descendant
is excluded. Only an explicit `subtasks` edge creates that hierarchy. Causation,
sequence, shared assignee, or Runbook branching never creates a child relation.

A leaf Task resolves one applicable accepted Runbook. The Runbook loads only
its required Skills; each Skill resolves exactly one Tool, and each Tool
resolves one real Source-backed Capability. Assigning the Task supplies that
closed dependency set. Agent Tool, Skill, and Runbook lists are not separate
grants or gates.
Missing or invalid links fail closed. Completion requires current evidence for
the Task's acceptance condition, not merely Runbook exhaustion or Tool delivery.

`Agent.tasks` is the sole manual work assignment. Accepted Runbooks declare
their Task and Agent applicability through `task` and `for_agent`; the authored
`Task.runbook` remains a procedure binding when applicable. The shared resolver
includes inherited guidance without selecting unrequested siblings, and its
exact dependencies feed execution, Reader, and graph membership.

When an assignment lacks an accepted procedure, `task.assigned` activates
[Generate Runbook](/Tasks/generate/runbook.md). Darwin chooses the minimal
required Skills from the accepted shared catalog and submits their exact refs
with the procedure. The assigned Task waits for approval; neither assignment
nor a draft Runbook grants the catalog or permits execution.

Task categories stay shallow. Executive groups Query and Computer Use, shared
by typed and spoken requests. Wiki exposes Ingest, Curate, Merge, Link, Improve,
Archive, Audit, and Check. Research exposes Question, Learn, News, and Model.
Generate exposes Tool, Skill, Task, and Runbook. Executive is a Knowledge
grouping rather than an executable coordinator Task. The [Observation lifecycle](/Agents/Executive/Architecture/observations.md)
is a Knowledge hierarchy whose only executable transitions are Compact beneath
Immediate and Promote beneath Durable. It defines the three memory levels and
retention rules behind those transitions.

Generate → Task authors reusable Task definitions with `vault.propose`.
`task.create` activates an exact accepted Task and never authors a Library
definition. A Task may declare multiple ordered triggers without changing its
identity.

Task selection, authored edges, the immutable Objective, and acceptance evidence
are recorded together for every attempt. The same Objective and resolved Article
refs drive model input and graph activity.

## Relationships

- `implements` [Golden ontology](/Agents/Executive/Architecture/action-ontology.md) — Task remains outcome while Runbook, Skill, Tool, and execution retain separate meanings.
- `related_to` [Activation packet protocol](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md) — The resolved Task spine supplies the packet's exact authority.
- `related_to` [Research requests](/Agents/Executive/Architecture/research-requests--7bf0113c.md) — Delegated research uses the same peer activation law.
- `related_to` [Real-time Executive](/Agents/Executive/Architecture/real-time-executive.md) — The speech connection delivers requests to the same ordinary work Tasks as typed Chat.
