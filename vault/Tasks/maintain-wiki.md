---
kind: task
last_run: 7fd1233f3fe8
schedule: 0 */6 * * *
status: pending
status_updated: '2026-08-20T10:33:01'
subtasks:
- '[[Tasks/ingest-sources]]'
- '[[Tasks/lint-notes]]'
- '[[Tasks/validate-links]]'
- '[[Tasks/categorize-notes]]'
- '[[Tasks/detect-contradictions]]'
- '[[Tasks/expand-stubs]]'
title: maintain-wiki
---

The self-maintenance loop (Wikipedia Task Center × llm-wiki): ingest new
sources, copyedit, validate links, categorize, detect contradictions, expand
stubs. Runs every six hours; all output lands in `_staging/` for owner review.
