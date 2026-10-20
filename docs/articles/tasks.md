# Tasks

A **Task** Article states a reusable outcome and its acceptance condition. It
is a definition, not a request: each event or user turn that asks for the
outcome creates one **Activation** in the execution ledger, and each attempt is
a **Run** (see [Ontology](../ontology/index.md#runtime-identities-activation-run-and-receipts)).

| Field (under `obsidience`) | Meaning |
| --- | --- |
| `assignee` | The accountable Agent. |
| `runbook` | The applicable Runbook. A leaf Task must resolve one, or activation fails closed. |
| `triggers` | Ordered events that activate the Task, such as `source.inbox` or `harness.degraded`. Triggers change bindings, never identity or acceptance. |
| `model`, `reasoning_effort` | Per-Task model choice and effort (`auto` uses the installation default). |
| `subtasks` | The only field that creates Task hierarchy. Hierarchy expresses scope, never sequence. |
| `enabled` | Defaults to true; `false` stops events from routing to the Task. |

A UI verb becomes a Task only when it names an independently queueable outcome
with its own acceptance condition. `task.create` activates an exact accepted
peer Task and records causation only; activation never authors a definition.

## How Tasks run

Scheduled, event and delegated Tasks run on the same Google ADK loop as the
Executive, with one in-memory session per Run:

- Each step is one native Tool call; only `task.complete` finishes, and a
  Tool-less reply is not a completion (three strikes fail the Run).
- Each step advertises only the Tools the controller state allows, with schemas
  that follow the active proposal and completion contract.
- Every Tool call commits intent before dispatch and an immutable receipt on
  return. Completed occurrences are never implicitly replayed.

**Admission order.** Ready Source Inbox heads first, then other bound events,
then periodic work; each class chronological, per-Task FIFO intact. Active Tasks
are never preempted. A conversation turn, an accepted wake or Realtime startup
closes autonomous admission and asks active work to yield; only the provider
request is cancelled, and the interrupted occurrence waits for explicit
disposition.

**Resources.** GPU reservations are checked before a Run claims capacity and
inside its model lease. A shortfall keeps the exact occurrence waiting with its
reason; denial before effects is not a failed Run.

Durable periodic schedules are not inherited from the development machine; the
starter Tasks are event-driven or delegated.

## Starter Vault Tasks

<!-- catalogue:tasks -->

Triggers marked *on request* activate only through `task.create` or an owner
request. The Task families: **Wiki** (Ingest, Curate, Merge, Link, Improve,
Archive), **Research** (Question, Learn), **Generate** (Tool, Skill, Task,
Runbook) and **Harness** (Audit, Repair, Model), plus `Tasks/query` for
specialist queries.
