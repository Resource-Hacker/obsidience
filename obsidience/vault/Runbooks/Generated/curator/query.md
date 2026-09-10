---
type: runbook
title: 'Runbook: Query (Alexandria)'
obsidience:
  approved_at: '2026-08-22T09:29:31'
  assignee: Agents/Alexandria/Alexandria
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  generated_by: '[[Runbooks/create-a-runbook]]'
  provenance: proposed by Darwin (task Tasks/generate/runbook)
  skills:
  - '[[Skills/observations.temporary.append]]'
  - '[[Skills/source.read]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.search]]'
  task: '[[Tasks/query]]'
---

# Runbook: Query (Alexandria)

## Prerequisites
- An active Query Task is provided with an activation packet containing the owner's question.

## Ordered Actions
1. **Analyze the Question**: Review the activation packet to understand the specific query and any provided context.
2. **Search for Context**: Follow [vault.search](/Skills/vault.search.md) and call `vault.search` to find relevant articles related to the query.
3. **Retrieve Relevant Articles**: Follow [vault.read](/Skills/vault.read.md) and call `vault.read` for the full content of the identified candidate articles.
4. **Synthesize and Verify**: Compare the retrieved information against the query. If the query requires external evidence, follow [source.read](/Skills/source.read.md) and call `source.read`.
5. **Preserve Useful State**: Only when it will help a later activation, follow [observations.temporary.append](/Skills/observations.temporary.append.md) and call `observations.temporary.append` with concise findings, decisions, blockers, and next actions. Never store private reasoning.
6. **Formulate Response**: Synthesize the findings into a clear, direct answer.
7. **Complete Task**: Follow [task.complete](/Skills/task.complete.md) and call `task.complete` to submit the final answer.

## Bounded Branches
- **Information Gap**: If the query cannot be answered with current vault knowledge, identify the specific missing information and suggest a research path.
- **Contradictory Evidence**: If multiple articles provide conflicting information, present all relevant viewpoints and note the uncertainty.

## Stop Conditions
- A direct, evidence-based answer is formulated.
- It is determined that the query cannot be answered with the available tools and knowledge.

## Completion Criteria
- The owner receives a concise, evidence-based answer.
- The task is closed with `task.complete` under [task.complete](/Skills/task.complete.md).

## Verification
- Ensure every part of the answer is grounded in a `vault.read` result or the activation packet.

## Recovery
- If `vault.search` yields no results, call it once more with broader or different descriptive terms.
- If `vault.read` fails due to an ambiguous reference, follow [vault.list](/Skills/vault.list.md) and call `vault.list` to locate the correct article path.
