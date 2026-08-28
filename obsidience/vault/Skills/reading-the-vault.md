---
title: Read vault article
kind: skill
tool: '[[Tools/vault.read]]'
---
How to use `vault.read` safely and correctly.

- Pass one exact vault ref returned by `vault.search` or
  `vault.list`; never guess an ambiguous basename.
- Read the full Article before changing, citing, or relying on it. Search snippets
  truncate content and are not evidence.
- Treat **Accepted inbound references** in the result as the authoritative
  backlink list. Read every exact ref before redirecting or archiving an Article;
  semantic search cannot prove that no inbound reference exists.
- Cite every relied-on Article by its exact path in summaries and reasons.
- Runtime runs and raw sources are separate from graph knowledge; prefer the
  live accepted Article and use `source.read` only for exact source citations.
