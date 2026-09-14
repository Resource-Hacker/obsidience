---
type: knowledge
title: Task activation
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/harness/execution/executor.py
- resource: obsidience/harness/execution/scheduler.py
- resource: obsidience/harness/execution/ledger.py
- resource: obsidience/harness/knowledge/dependencies.py
---

A reusable Task Article may be activated manually, by a graph or shell event,
a schedule, or exact `task.create`. Chat and voice normally enter the
Agent-owned Executive session and native DeepSeek loop; they activate a specialist
Task only when a separately queueable outcome is requested. Each requested occurrence receives an activation identity
and each attempt has a run identity linked to it. The existing SQLite ledger
owns those occurrences, their original objectives, bound parameters and receipts.
The Task status/FIFO is a compatibility projection. A new request never inherits
a previous target; completed effects are not automatically replayed.

The Tasks pane is a filtered operational matrix. It shows only Tasks with a
schedule, event trigger, or active execution. It is not the Task repository; the
shared Task hierarchy lives in Library.

A selected parent includes its descendant Task scope unless an exact descendant
is excluded. Only an explicit `subtasks` edge creates that hierarchy. Causation,
sequence, shared assignee, or Runbook branching never creates a child relation.
Selecting a taxonomy container does not execute its descendants; choose a Task
with an accepted procedure. Evidenced independent occurrences may progress past
a terminal head, but unknown effects still require disposition.

A leaf Task resolves one applicable accepted Runbook. The Runbook loads only
its required Skills; each Skill resolves exactly one Tool, and each Tool
resolves one real Source-backed Capability. Assigning the Task supplies that
closed dependency set. Agent Tool, Skill, and Runbook lists are not separate
grants or gates.
Missing or invalid links fail closed. Completion requires current evidence for
the Task's acceptance condition, not merely Runbook exhaustion or Tool delivery.

`Agent.tasks` assigns separately queueable work. `Agent.skills` declares
the available conversational capabilities through exact paired Tool bindings.
Standing Executive instructions live in the Agent identity itself. Accepted Runbooks declare
their Task and Agent applicability through `task` and `for_agent`; the authored
`Task.runbook` remains a procedure binding when applicable. The shared resolver
includes inherited guidance without selecting unrequested siblings, and its
exact dependencies feed execution, Reader, and graph membership.

When an assignment lacks an accepted procedure, `task.assigned` activates
[Generate Runbook](/Tasks/generate/runbook.md). Darwin chooses the minimal
required Skills from the accepted shared catalog and submits their exact refs
with the procedure. The assigned Task waits for approval; neither assignment
nor a draft Runbook grants the catalog or permits execution.

Task categories stay shallow. Chat and voice create Agent-owned runs rather than an Executive Task.
The shared Query definition remains for existing specialist question procedures. Wiki exposes Ingest, Curate, Merge, Link, Improve,
Archive, Audit, Check, and Repair. Research exposes Question, Learn, Distill, and Model.
Generate exposes Tool, Skill, Task, and Runbook. The Executive family remains a Knowledge grouping for independently queueable
Query work. The universal Executive Task is retired. The [Observation lifecycle](/Agents/Executive/Architecture/Harness/observations.md)
is a Knowledge hierarchy whose only executable transitions are Compact beneath
Immediate and Promote beneath Durable. It defines the three memory levels and
retention rules behind those transitions.

Generate → Task authors reusable Task definitions with `vault.propose`.
`task.create` activates an exact accepted Task and never authors a Library
definition. A Task may declare multiple ordered triggers without changing its
identity.

Task selection, authored edges, the immutable Objective, and acceptance evidence
are recorded together for every attempt. The same Objective and resolved Article
refs drive model input and graph activity. Each Tool dispatch records intent
before execution and a terminal receipt afterward. Interrupted or uncertain
effects require disposition; a restart or expired schedule is not permission
to replay them.

## Relationships

- `implements` [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md) — Task remains outcome while Runbook, Skill, Tool, and execution retain separate meanings.
- `related_to` [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — The resolved Task spine supplies the packet's exact authority.
- `related_to` [Research requests](/Agents/Executive/Architecture/Harness/research-requests--7bf0113c.md) — Delegated research uses the same peer activation law.
- `related_to` [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md) — Speech and typed Chat share Agent-owned admission, packet routing and execution.

The [Cordis composition](/Agents/Executive/Architecture/Harness/cordis-composition.md) contract keeps implementation dependencies explicit and pairs each owned runtime effect with cleanup.
