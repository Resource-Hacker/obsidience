---
action: create
agent: Darwin
assignee: Agents/Heimdall/Heimdall
event_context:
  checkout_event_id: checkout-18ce29a2b969c2d9
  output_runbook: Runbooks/Generated/guardian/query.md
  queued_at: '2026-08-22T08:18:00'
  skills:
  - Skills/harness.status
  - Skills/observations.temporary.append
  - Skills/source.read
  - Skills/task.complete
  - Skills/task-authoring
  - Skills/vault.list
  - Skills/vault.propose
  - Skills/vault.read
  - Skills/vault.search
  - Skills/vault.validate
  target_agent: Agents/Heimdall/Heimdall
  target_agent_name: Heimdall
  target_task: Tasks/query
  target_task_article: 'Answer the owner''s current question from the graph and its
    activation

    briefing. Query is interactive work, not a scheduled maintenance Task.'
  target_task_hierarchy:
  - Tasks/query
  target_task_title: Query
  tools:
  - Tools/harness.status
  - Tools/observations.temporary.append
  - Tools/source.read
  - Tools/task.complete
  - Tools/task.create
  - Tools/vault.list
  - Tools/vault.propose
  - Tools/vault.read
  - Tools/vault.search
  - Tools/vault.validate
kind: runbook
proposal: true
proposed_at: '2026-08-22T08:20:05'
reason: Generated a task-specific Runbook for Heimdall to execute the Query task,
  following the 'Generate runbook procedure' instructions.
rejected_at: '2026-08-22T09:00:00'
rejected_reason: Superseded by the deterministic checkout Runbook quality-gate repair.
runbook: Runbooks/Generated/guardian/query.md
target: Runbooks/Generated/guardian/query.md
task: Tasks/generate/runbook
title: Heimdall Query Runbook
---

# Runbook: Query (Heimdall)

## Prerequisites
- The `Tasks/query` task is activated via a `task.checkout` event.
- The owner's question is provided in the activation briefing or current graph context.
- The environment is stable (verified via `Skills/harness.status`).

## Ordered Actions
1. **Identify Information Needs**: Use `Skills/vault.search` to locate relevant existing knowledge and `Skills/vault.list` to enumerate potential context.
2. **Gather Evidence**: Use `Skills/vault.read` to retrieve full articles and `Skills/source.read` to verify content against direct `source://` citations.
3. **Monitor Progress**: Use `Skills/observations.temporary.append` to record significant findings, decisions, or blockers during the investigation.
4. **Synthesize Response**: Formulate a concise answer based on the gathered evidence.
5. **Propose Knowledge Updates**: If the query reveals the need for new knowledge or corrections, use `Skills/vault.propose` to stage a proposal.
6. **Verify Integrity**: Use `Skills/vault.validate` to ensure any proposed changes or retrieved data maintain graph integrity.
7. **Complete Task**: Use `Skills/task.complete` to submit the final answer and end the session.

## Stop Conditions
- A complete and accurate answer is formulated.
- A terminal error occurs that cannot be recovered from using the provided tools.
- The owner's question is determined to be outside the scope of available tools/knowledge.

## Recovery
- If a search fails to yield results, broaden the query using `Skills/vault.search` or check status via `Skills/harness.status`.
- If a reading operation fails, verify the reference using `Skills/vault.list`.
- If a proposal is rejected, review the error and use `Skills/vault.propose` to submit a corrected version.

## Completion Criteria
- The owner's question is answered directly.
- The task is closed with `Skills/task.complete` with a status of `completed` or `failed`.
