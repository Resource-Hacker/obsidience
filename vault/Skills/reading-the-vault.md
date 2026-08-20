---
title: reading-the-vault
kind: skill
tools: [vault.list, vault.search, vault.read, vault.validate]
---
How to read the vault safely and efficiently.

- To enumerate a folder ("check every task"), use `vault.list` — it is
  deterministic and complete; search is for finding by meaning.
- Search before you read; search again with different words before concluding
  something does not exist (hybrid search misses exact strings sometimes —
  vary phrasing).
- Never act on a snippet: `vault.read` the full note first. Snippets truncate
  mid-sentence and hide frontmatter.
- Cite every note you relied on as a [[wikilink]] in summaries and reasons.
- Receipts/ notes are history, not current truth; prefer the live note.
- Queries are plain words ("task frontmatter runbook"), NOT operators —
  `path:`, `kind:`, and `tag:` filters do not exist here.
