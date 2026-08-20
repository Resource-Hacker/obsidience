---
blocked_reason: null
kind: task
last_run: 3128f3a4b03c
schedule: 0 */6 * * *
status: running
status_updated: '2026-08-20T11:00:03'
subtasks:
- '[[Tasks/ingest]]'
- '[[Tasks/copyedit]]'
- '[[Tasks/validate-links]]'
- '[[Tasks/categorize-notes]]'
- '[[Tasks/contradictions]]'
- '[[Tasks/improve]]'
title: Wiki
---

The wiki maintenance loop (karpathy llm-wiki method): ingest new sources,
copyedit, validate links, categorize, check contradictions, then improve the
weakest article. Query is the live Operator chat. Runs every six hours; every
change waits in _staging/ for owner review.
