---
type: skill
title: Using vault.read
obsidience:
  tool: '[[Tools/vault.read]]'
---

Use `vault.read` to read bounded pages of one accepted Article and its
deterministic inbound graph references.

- Begin with `{"ref": str}` using one exact vault ref or exact Markdown path.
  Do not guess an ambiguous title or basename.
- Success returns an `Article` identity envelope, `view_sha256`, exact character
  range and up to 8,000 characters from the Article title/body and its `Accepted
  inbound references` section. Backlink presentation is capped at 24 and states
  when more exist. A bounded native document lifecycle projection shows `status`, `freshness`,
  and optional `stale_after`; it is not Task execution state or verification.
  Other frontmatter authority metadata is not part of this view.
- Continue only when missing text is needed: pass the exact `ref`, returned
  next `offset`, and `expected_sha256` equal to the prior `view_sha256`.
  The hash covers the complete Article, lifecycle and backlink snapshot. An
  expiry crossing also changes this view. A changed view
  returns no replacement text; do not treat a new version as old evidence.
  Read offset zero without an expected hash only to explicitly obtain a new view.
- An earlier request may project already-consumed pages to their identity and
  retained prefix. Follow its exact version-checked recovery instruction when
  omitted text is needed; do not infer what the omitted text says.
- Treat only the returned exact refs as observed backlinks for that snapshot.
  A capped return must not be described as complete beyond its explicit bounds.
- Stop on `Note not found` or an unavailable read. Do not retry with a similar
  title, infer missing content, or treat a partial return as the full Article.
