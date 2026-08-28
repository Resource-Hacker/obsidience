---
assignee: '[[Agents/Heimdall/Heimdall]]'
kind: task
last_run: 6323adcedc07
model: obsidience-qwen38-27b-q8
reasoning_effort: xhigh
runbook: '[[Runbooks/check]]'
schedule: 30 */6 * * *
status: completed
status_updated: '2026-08-28T05:30:52'
summary: 'Harness status was observed as healthy in one read-only snapshot: status
  healthy, graph nodes 218, graph links 396, notes 161, source files 385, source issues
  0, tasks 21, tasks by status completed 8, draft 11, failed 1, running 1, recent
  runs 20, recent failures 3, and reviews pending 0. The bounded recent failures and
  failed task are reported as observed ledger state, not diagnosed as current root
  causes.'
taxonomy_path: wiki/check
title: Check
---

Inspect one deterministic Obsidience harness snapshot and report its observed
health without shell access, repair attempts, or inferred success.
