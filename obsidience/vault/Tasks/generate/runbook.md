---
assignee: '[[Agents/Darwin/Darwin]]'
generated_runbook: '[[Runbooks/Generated/researcher/query]]'
kind: task
last_run: 850980ec98b9
model: obsidience-qwen38-27b-q8
triggers:
- task.checkout
params:
  checkout_event_id: checkout-18ce2c5bfb2d3187
  output_runbook: Runbooks/Generated/researcher/query.md
  queued_at: '2026-08-22T09:07:55'
  skills:
  - Skills/appending-temporary-observations
  - Skills/capturing-source-evidence
  - Skills/reading-source-evidence
  - Skills/completing-a-task
  - Skills/activating-a-task
  - Skills/listing-the-vault
  - Skills/proposing-changes
  - Skills/reading-the-vault
  - Skills/searching-the-vault
  - Skills/validating-the-vault
  - Skills/fetching-web-sources
  - Skills/searching-the-web
  target_agent: Agents/Darwin/Darwin
  target_agent_name: Darwin
  target_task: Tasks/query
  target_task_article: 'Answer the owner''s current question from the graph and its
    activation

    briefing. Query is interactive work, not a scheduled maintenance Task.'
  target_task_hierarchy:
  - Tasks/query
  target_task_title: Query
  tools:
  - Tools/observations.temporary.append
  - Tools/source.ingest
  - Tools/source.read
  - Tools/task.complete
  - Tools/task.create
  - Tools/vault.list
  - Tools/vault.propose
  - Tools/vault.read
  - Tools/vault.search
  - Tools/vault.validate
  - Tools/web.fetch
  - Tools/web.search
reasoning_effort: xhigh
runbook: '[[Runbooks/create-a-runbook]]'
status: completed
status_updated: '2026-08-22T09:29:34'
title: Runbook
triggered_at: '2026-08-22T09:07:55'
---

The executable Runbook child of the top-level Generate Task. A `task.checkout` graph event
activates this regular Task with the exact checked-out Task, target agent,
available Tools, paired Skills, and output Runbook ref as parameters. Darwin
generates the per-agent Runbook through the ordinary graph.
