---
approved_at: '2026-08-22T09:29:34'
assignee: Agents/Darwin/Darwin
for_agent: '[[Agents/Darwin/Darwin]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/capturing-source-evidence]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/searching-the-web]]'
task: '[[Tasks/query]]'
title: 'Runbook: Query (Darwin)'
---

# Runbook: Query (Darwin)

## Prerequisites
- `Tasks/query` is activated with a specific question.
- Access to the provided suite of Tools and Skills.

## Ordered Actions
1. **Discovery**: Use `Skills/searching-the-vault` to check for existing knowledge related to the query. Use `Skills/searching-the-web` to find external information.
2. **Acquisition**: Use `Skills/fetching-web-sources` to retrieve content from web results. Use `Skills/capturing-source-evidence` to ingest all relevant material.
3. **Verification**: Use `Skills/reading-source-evidence` to confirm the accuracy and relevance of the captured material.
4. **Synthesis**: Formulate a concise answer based on the verified evidence.
5. **Reporting**: Use `Skills/appending-temporary-observations` to note any significant findings, decisions, or blockers during the process.
6. **Completion**: Use `Skills/completing-a-task` to provide the final answer.

## Bounded Branches
- **Information Gap**: If `Skills/searching-the-vault` and `Skills/searching-the-web` yield no relevant results, use `Skills/appending-temporary-observations` to record the gap and complete with `status: "failed"`.
- **Tool Failure**: If a tool fails, use `Skills/appending-temporary-observations` to record the error and attempt one retry or complete with `status: "failed"`.

## Stop Conditions
- A complete answer is formulated.
- No further information can be retrieved.
- A terminal error occurs.

## Completion Criteria
- The owner's question is answered directly using the synthesized evidence.

## Verification
- Ensure the answer is grounded in the `source://` citations captured during the process.

## Recovery
- If a search fails, try alternative keywords using `Skills/searching-the-web`.
- If a fetch fails, attempt to find an alternative source via `Skills/searching-the-web`.
