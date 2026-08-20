---
blocked_reason: null
kind: task
last_run: 3128f3a4b03c
schedule: 0 */6 * * *
status: running
status_updated: '2026-08-20T11:00:03'
subtasks:
- '[[Tasks/ingest-sources]]'
- '[[Tasks/lint-notes]]'
- '[[Tasks/validate-links]]'
- '[[Tasks/categorize-notes]]'
- '[[Tasks/detect-contradictions]]'
- '[[Tasks/expand-stubs]]'
title: Wiki
---

The self-maintenance loop (Wikipedia Task Center × llm-wiki): ingest new
sources, copyedit, validate links, categorize, detect contradictions, expand
stubs. Runs every six hours; all output lands in `_staging/` for owner review.
