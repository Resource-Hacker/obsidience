---
approved_at: '2026-08-22T09:29:30'
assignee: Agents/Heimdall/Heimdall
binding: Tasks/query
for_agent: '[[Agents/Heimdall/Heimdall]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
runbook: Runbooks/Generated/guardian/query.md
skills:
- '[[Skills/checking-harness-status]]'
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
title: Query Runbook
---

# Runbook: Query

## Prerequisites
- Task `Tasks/query` is active for `Agents/Heimdall/Heimdall`.

## Ordered Actions
1. **Identify Goal**: Use `Skills/searching-the-vault` and `Skills/reading-the-vault` to identify the question.
2. **Gather Evidence**: Use `Skills/searching-the-vault` and `Skills/reading-the-vault` to find answers. Use `Skills/reading-source-evidence` for external sources.
3. **Log Progress**: Use `Skills/appending-temporary-observations` to track findings.
4. **Resolve**: Use `Skills/completing-a-task` to answer, or `Skills/task-authoring` to propose a follow-up.

## Bounded Branches
- **Unclear Goal**: Use `Skills/searching-the-vault` or propose a clarification task.
- **Missing Info**: Use `Skills/searching-the-vault` with broader terms.

## Stop Conditions
- Question answered.
- Follow-up task proposed.
- No more information available.

## Completion Criteria
- A definitive answer or next-step proposal is provided.

## Verification
- Response addresses the activation briefing.

## Recovery
- Use `Skills/listing-the-vault` if `Skills/reading-the-vault` fails.
