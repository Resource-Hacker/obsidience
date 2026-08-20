---
title: lint-notes
kind: runbook
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
One lint pass over vault notes.

1. `vault.search` for notes with obvious defects: missing frontmatter fields
   (title/kind), TODO markers, malformed headings, or empty bodies.
2. `vault.read` each candidate fully.
3. Stage at most three `vault.propose` fixes (action `update`, full body).
4. If nothing needs fixing, complete with status "completed" and say so —
   an empty pass is a valid result.
