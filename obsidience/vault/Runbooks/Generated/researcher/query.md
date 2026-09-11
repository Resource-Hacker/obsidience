---
type: runbook
title: 'Runbook: Query (Darwin)'
obsidience:
  approved_at: '2026-08-22T09:29:34'
  assignee: Agents/Darwin/Darwin
  for_agent: '[[Agents/Darwin/Darwin]]'
  generated_by: '[[Runbooks/create-a-runbook]]'
  provenance: proposed by Darwin (task Tasks/generate/runbook)
  skills:
  - '[[Skills/observations.temporary.append]]'
  - '[[Skills/source.ingest]]'
  - '[[Skills/source.read]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/web.fetch]]'
  - '[[Skills/web.search]]'
  task: '[[Tasks/query]]'
---

# Runbook: Query (Darwin)

## Prerequisites
- `Tasks/query` is activated with a specific question.
- Access to the provided suite of Tools and Skills.

## Ordered Actions
1. **Discovery**: Follow [vault.search](/Skills/vault.search.md) and call `vault.search` to check for existing knowledge. When current external evidence is required, follow [web.search](/Skills/web.search.md) and call `web.search`.
2. **Acquisition**: Follow [web.fetch](/Skills/web.fetch.md) and call `web.fetch` for the selected direct sources. Follow [source.ingest](/Skills/source.ingest.md) and call `source.ingest` for only the relevant material.
3. **Verification**: Follow [source.read](/Skills/source.read.md) and call `source.read` to confirm the captured material's accuracy and relevance.
4. **Synthesis**: Formulate a concise answer based on the verified evidence.
5. **Reporting**: Only when it will help a later activation, follow [observations.temporary.append](/Skills/observations.temporary.append.md) and call `observations.temporary.append` with concise findings, decisions, blockers, and next actions. Never store private reasoning.
6. **Completion**: Follow [task.complete](/Skills/task.complete.md) and call `task.complete` to provide the final answer.

## Bounded Branches
- **Information Gap**: If `vault.search` and `web.search` yield no relevant results, preserve the exact gap only when useful later and complete with `status: "failed"`.
- **Tool Failure**: Record only the durable blocker when useful later, then attempt one safe retry or complete with `status: "failed"`.

## Stop Conditions
- A complete answer is formulated.
- No further information can be retrieved.
- A terminal error occurs.

## Completion Criteria
- The owner's question is answered directly using the synthesized evidence.

## Verification
- Ensure the answer is grounded in the `source://` citations captured during the process.

## Recovery
- If `web.search` fails, call it once more with alternative keywords.
- If `web.fetch` fails, call `web.search` once for an alternative direct source.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Record observable findings and decisions, not a narration of routine work.
