---
approved_at: '2026-08-21T10:42:02'
assignee: Heimdall
for_agent: '[[Agents/Heimdall/Heimdall]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
runbook: Runbooks/Generated/guardian/wiki/guard.md
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/task-authoring]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
task: '[[@library/Tasks/wiki/guard]]'
title: 'Runbook: guard'
---

# Runbook: guard

## Overview
Coordinates the guardian functions (review, audit, monitor, moderate, and recover) to maintain vault integrity, compliance, and operational stability.

## Prerequisites
- Access to the `guard` subtask hierarchy: `review`, `audit`, `monitor`, `moderate`, and `recover`.
- Ability to observe vault state, agent behaviors, and task execution logs.

## Procedure

### 1. Monitor and Audit (Proactive)
- **Monitor**: Execute `monitor` procedures to detect drift, failures, or risks in the vault, agents, or scheduled jobs.
- **Audit**: Execute `audit` procedures to verify compliance, quality, freshness, and integrity of articles and graph structures.

### 2. Review and Verify (Reactive/Intake)
- **Review**: Execute `review` procedures for incoming tasks, changes, or manifest/identity/scope/risk assessments.
- **Verify**: Perform deep verification of claims, citations, provenance, and schema adherence as specified by the `review/verify` hierarchy.

### 3. Moderate and Protect (Enforcement)
- **Moderate**: Execute `moderate` procedures to apply protections, quarantine non-compliant content, or manage content lifecycles (archive, purge, etc.).

### 4. Recover and Remediate (Response)
- **Recover**: Execute `recover` procedures (revert, rollback, restore, rebuild, or reindex) when monitoring or audit detects corruption, failure, or drift.

## Stop Conditions
- All scheduled monitoring and audit cycles are completed without pending alerts.
- No active `review` or `moderate` actions are in progress.

## Completion Criteria
- The `guard` session has successfully coordinated all required subtask executions and verified the current state of the vault against defined policies.

## Recovery
- If a `guard` procedure fails, escalate to the owner or use `recover` procedures to restore the guardian's operational state.
