---
type: runbook
title: 'Runbook: Query (Darwin)'
obsidience:
  assignee: Agents/Darwin/Darwin
  for_agent: '[[Agents/Darwin/Darwin]]'
  skills:
  - '[[Skills/observations.retain]]'
  - '[[Skills/source.ingest]]'
  - '[[Skills/source.read]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/web.fetch]]'
  - '[[Skills/web.search]]'
  - '[[Skills/observations.recall]]'
  task: '[[Tasks/query]]'
---


# Runbook: Query (Darwin)

## Prerequisites
- `Tasks/query` is activated with a specific question.
- Access to the provided suite of Tools and Skills.

## Ordered Actions
1. **Discovery**: Follow [vault.search](/Skills/vault.search.md) and call `vault.search` to check for existing knowledge. When current external evidence is required, follow [web.search](/Skills/web.search.md) and call `web.search`.
2. **Acquisition**: Follow [web.fetch](/Skills/web.fetch.md) and call `web.fetch` for the selected direct sources. `web.fetch` already captures an immutable Source; reuse its exact citation. Use [source.ingest](/Skills/source.ingest.md) only for independent material that has no captured Source, never to duplicate a fetched page or copy its preview into a second Source.
3. **Verification**: Assess the inspected captured bytes for authority, date, accuracy, and relevance. A `web.fetch` preview supports only its returned range. Use [source.read](/Skills/source.read.md) to read additional bytes when needed for the answer; never infer an unread tail. A Source that activates the Task must be read completely before relying on it.
4. **Synthesis**: Formulate a concise answer based on the verified evidence.
5. **Reporting**: Only when it will help a later activation, follow [observations.retain](/Skills/observations.retain.md) and call `observations.retain` with concise findings, decisions, blockers, and next actions. Never store private reasoning.
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


When a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Record observable findings and decisions, not a narration of routine work.
