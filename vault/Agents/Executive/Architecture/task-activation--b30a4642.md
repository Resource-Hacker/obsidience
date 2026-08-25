---
approved_at: '2026-08-25T05:44:33'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/merge)
title: Task activation
---

Obsidience has one Task object and several activation methods. A Task is a
reusable outcome definition. Manual invocation, voice or graph events, and
schedules activate it. Runtime state belongs to the execution ledger and the
Tasks pane, not to another object type.

The Tasks pane is a filtered operational matrix. It shows only Tasks with a
schedule, event trigger, or active execution. It is not the Task repository;
the shared Task hierarchy lives in Library.

A parent Task includes its descendant Task scope unless an exact descendant is
excluded. Only an explicit `subtasks` edge creates that hierarchy. One Task may
use `task.create` to activate another exact accepted Task. The target retains
its authored hierarchy; activation provenance never creates a child or subtask
relation.

A leaf Task must resolve one Runbook. The Runbook resolves its Skills, each
Skill resolves exactly one Tool, and the Agent checkout may narrow the resulting
capability set. Missing or invalid links fail closed. Completion requires the
Task's acceptance conditions, not merely reaching the end of the Runbook.

Task families remain shallow by default: Wiki directly exposes Ingest, Query,
Curate, Merge, Link, Improve, Archive, Audit, and Check; Research exposes
Question, Learn, News, and Model; Generate is a peer; Observations keeps deeper Temporary and
Durable lifecycles because those scopes are independently meaningful.

Generate → Task authors reusable Task definitions with `vault.propose`.
`task.create` activates an exact accepted Task and never authors a Library
definition.

Each named Agent has one canonical Agent Brain Article. A parallel Knowledge
role charter for the same Agent is redundant migration material: Merge absorbs
its unique detail and relationships into the Agent Article, redirects inbound
references, and stages the shadow for archival.

## Relationships

- `governs` [[Agents/Darwin/Darwin|Darwin]] - Darwin owns Research and Generate outcomes.
- `governs` [[Agents/Alexandria/Alexandria|Alexandria]] - Alexandria owns Ingest, Curate, Merge, Link, Improve, and Archive outcomes.
- `governs` [[Agents/Executive/Subagents/heimdall-guardian-role--3d93da53|Heimdall role charter]] - Heimdall owns Audit and Check outcomes.
