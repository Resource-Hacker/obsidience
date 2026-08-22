---
approved_at: '2026-08-22T09:29:31'
assignee: Agents/Alexandria/Alexandria
for_agent: '[[Agents/Alexandria/Alexandria]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/task-authoring]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
task: '[[Tasks/query]]'
title: 'Runbook: Query (Alexandria)'
---

# Runbook: Query (Alexandria)

## Prerequisites
- An active Query Task is provided with an activation briefing containing the owner's question.

## Ordered Actions
1. **Analyze the Question**: Review the activation briefing to understand the specific query and any provided context.
2. **Search for Context**: Use `Skills/searching-the-vault` to find relevant articles related to the query.
3. **Retrieve Relevant Articles**: Use `Skills/reading-the-vault` to read the full content of the identified candidate articles.
4. **Synthesize and Verify**: Compare the retrieved information against the query. If the query requires external evidence, use `Skills/reading-source-evidence`.
5. **Document Reasoning**: Use `Skills/appending-temporary-observations` to record intermediate findings or decisions.
6. **Formulate Response**: Synthesize the findings into a clear, direct answer.
7. **Complete Task**: Use `Skills/completing-a-task` to submit the final answer.

## Bounded Branches
- **Information Gap**: If the query cannot be answered with current vault knowledge, identify the specific missing information and suggest a research path.
- **Contradictory Evidence**: If multiple articles provide conflicting information, present all relevant viewpoints and note the uncertainty.

## Stop Conditions
- A direct, evidence-based answer is formulated.
- It is determined that the query cannot be answered with the available tools and knowledge.

## Completion Criteria
- The owner receives a concise, evidence-based answer.
- The task is closed via `Skills/completing-a-task`.

## Verification
- Ensure every part of the answer is grounded in a `Skills/reading-the-vault` result or the activation briefing.

## Recovery
- If `Skills/searching-the-vault` yields no results, attempt `Skills/searching-the-vault` again with broader or different descriptive terms.
- If `Skills/reading-the-vault` fails due to an ambiguous reference, use `Skills/listing-the-vault` to locate the correct article path.
