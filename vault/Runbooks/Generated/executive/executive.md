---
approved_at: '2026-08-21T10:19:35'
assignee: Agent/Obsidience
for_agent: '[[Agent/Obsidience]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
runbook: Runbooks/research/runbook
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/task-authoring]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
task: '[[@library/Tasks/executive]]'
title: 'Runbook: executive'
---

# Runbook: executive

## Overview
This Runbook provides the operational procedure for the JARVIS executive agent to manage requests by routing them to the appropriate subtask families.

## Prerequisites
- Access to all subtask families: conversation, computer, knowledge, research, delegation, and operations.
- Ability to identify the intent of the user request.

## Procedure

### 1. Intent Analysis
- Analyze the incoming request to determine the primary domain of action.
- Map the request to one or more of the following subtask families:
    - **Conversation**: For natural language interaction and clarification.
    - **Computer**: For interacting with the local environment or launching applications.
    - **Knowledge**: For retrieving or relating information from the vault.
    - **Research**: For gathering new information from external sources.
    - **Delegation**: For assigning or reconciling tasks.
    - **Operations**: For planning, scheduling, or monitoring processes.

### 2. Routing
- Select the most relevant subtask family based on the analysis.
- If the request is multi-faceted, sequence the subtask activations logically (e.g., Research $\rightarrow$ Knowledge $\rightarrow$ Conversation).
- Activate the selected subtask family.

### 3. Execution & Monitoring
- Monitor the execution of the activated subtask.
- If a subtask requires further clarification, route back to the **Conversation** subtask.
- If a subtask fails, initiate the recovery procedure defined in that subtask's specific Runbook.

## Stop Conditions
- The task is complete when the user's request has been addressed and the final response is delivered via the **Conversation** subtask.
- The task fails if a required subtask family is unavailable or if the intent cannot be mapped to any known subtask.

## Verification
- Confirm that the outcome of the subtask(s) directly satisfies the original request.
- Ensure the final state is communicated clearly to the user.

## Recovery
- If a subtask fails, attempt one retry if the subtask Runbook allows; otherwise, report the failure via the **Conversation** subtask.
