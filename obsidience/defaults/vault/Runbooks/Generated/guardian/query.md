---
type: runbook
title: Query Runbook
obsidience:
  assignee: Agents/Heimdall/Heimdall
  binding: Tasks/query
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  runbook: Runbooks/Generated/guardian/query.md
  skills:
  - '[[Skills/observations.retain]]'
  - '[[Skills/source.read]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/observations.recall]]'
  - '[[Skills/harness.status]]'
  task: '[[Tasks/query]]'
---


# Runbook: Query

## Prerequisites
- Task `Tasks/query` is active for `Agents/Heimdall/Heimdall`.

## Ordered Actions
1. **Identify Goal**: Follow [vault.search](/Skills/vault.search.md) and [vault.read](/Skills/vault.read.md), then call `vault.search` and `vault.read` to identify the question and accepted context.
2. **Gather Evidence**: For current Harness health, follow [harness.status](/Skills/harness.status.md) and call `harness.status` once. Distinguish current findings from historical runs, acknowledged warnings and unresolved effects. Query remains read-only; identify the exact Repair or Audit Task when action is needed. Reuse accepted context. For external evidence, follow [source.read](/Skills/source.read.md) and call `source.read`.
3. **Preserve Useful State**: Only when it will help a later activation, follow [observations.retain](/Skills/observations.retain.md) and call `observations.retain` with concise findings, decisions, blockers, and next actions. Never store private reasoning.
4. **Resolve**: Follow [task.complete](/Skills/task.complete.md) and call `task.complete` to answer. If a distinct accepted
   Task is required, report its exact ref for activation rather than inventing
   an ad hoc follow-up.

## Bounded Branches
- **Unclear Goal**: Call `vault.search` once with a clearer description or request clarification.
- **Missing Info**: Call `vault.search` once with broader terms.

## Stop Conditions
- Question answered.
- Exact accepted follow-up Task identified.
- No more information available.

## Completion Criteria
- A definitive answer or next-step proposal is provided.

## Verification
- Response addresses the activation packet.

## Recovery
- If `vault.read` fails due to an ambiguous reference, follow [vault.list](/Skills/vault.list.md) and call `vault.list` to find the exact path.


When a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Record observable findings and decisions, not a narration of routine work.
