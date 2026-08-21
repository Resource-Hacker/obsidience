---
approved_at: '2026-08-21T10:18:32'
assignee: Darwin
for_agent: '[[Agents/Darwin/Darwin]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
runbook: Runbooks/Generated/researcher/observations.md
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/task-authoring]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
task: '[[@library/Tasks/observations]]'
title: observations
---

# observations

Coordinate the lifecycle of temporary and durable observations.

## Prerequisites
- Target Task: [[@library/Tasks/observations|observations]]
- Target Agent: Darwin

## Ordered Actions
1. **Manage Temporary Observations**
   - Execute the subtask [[@library/Tasks/observations/temporary|temporary]] to handle transient findings.
   - Use [[Skills/appending-temporary-observations|appending-temporary-observations]] to record new evidence.
   - Follow the subtask hierarchy for `maintain` and `expire` phases.
2. **Manage Durable Observations**
   - Execute the subtask [[@library/Tasks/observations/durable|durable]] to handle distilled knowledge.
   - Follow the subtask hierarchy for `maintain`, `distill`, and `stage` phases.

## Stop Conditions
- All subtasks in the hierarchy are completed or terminated.
- A critical failure in a subtask prevents further coordination.

## Completion Criteria
- All subtasks under [[@library/Tasks/observations|observations]] have reached a terminal state.
- The task is ended using [[Skills/completing-a-task|completing-a-task]].

## Recovery
- If a subtask fails, report the failure via [[Skills/completing-a-task|completing-a-task]] and stop coordination.
