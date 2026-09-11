---
type: runbook
title: Query Runbook
obsidience:
  approved_at: '2026-08-22T09:29:30'
  assignee: Agents/Heimdall/Heimdall
  binding: Tasks/query
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  generated_by: '[[Runbooks/create-a-runbook]]'
  provenance: proposed by Darwin (task Tasks/generate/runbook)
  runbook: Runbooks/Generated/guardian/query.md
  skills:
  - '[[Skills/observations.temporary.append]]'
  - '[[Skills/source.read]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.search]]'
  task: '[[Tasks/query]]'
---

# Runbook: Query

## Prerequisites
- Task `Tasks/query` is active for `Agents/Heimdall/Heimdall`.

## Ordered Actions
1. **Identify Goal**: Follow [vault.search](/Skills/vault.search.md) and [vault.read](/Skills/vault.read.md), then call `vault.search` and `vault.read` to identify the question and accepted context.
2. **Gather Evidence**: Reuse those results. For external evidence, follow [source.read](/Skills/source.read.md) and call `source.read`.
3. **Preserve Useful State**: Only when it will help a later activation, follow [observations.temporary.append](/Skills/observations.temporary.append.md) and call `observations.temporary.append` with concise findings, decisions, blockers, and next actions. Never store private reasoning.
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


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Record observable findings and decisions, not a narration of routine work.
