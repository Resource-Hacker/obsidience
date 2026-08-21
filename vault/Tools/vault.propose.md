---
approved_at: '2026-08-21T04:02:35'
binding: builtin:vault.propose
kind: tool
provenance: proposed by Codex (task research generation kit)
title: vault.propose
---

Stage a note change for owner review — never writes the accepted vault directly.

args: `{"action": "create|update", "target": "Folder/name.md", "title": str, "body": str, "reason": str, "metadata": object}`.

`metadata` is optional and accepts only safe authored fields: `kind`, `binding`, `tool`, `skills`, `runbook`, `assignee`, `reasoning_effort`, `owner_maintained`, and the four recursive child fields. Use it when a typed graph article needs frontmatter. `update` must carry the FULL corrected body; accepted metadata not named by the proposal is preserved. Unknown metadata fields fail closed.
