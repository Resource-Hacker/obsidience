---
type: tool
title: vault.read
obsidience:
  binding: capability:vault.read
  source: obsidience/harness/capabilities/vault/read.py
---

Read one bounded page of an accepted Article view using its exact ref:
`{"ref": "Folder/name", "offset": 0, "expected_sha256": "optional prior view_sha256"}`.
The result includes its canonical ref, a revision hash, exact character range,
and up to 8,000 characters. The complete view begins with native document lifecycle (`status`,
`freshness`, and optional `stale_after`), then contains the Article text followed
by up to 24 deterministic inbound refs; paging does not silently truncate the
Article. A nonzero offset requires the prior `view_sha256` as `expected_sha256`.
The hash covers the Article, lifecycle and complete backlink snapshot. An
expiry crossing invalidates an older view without rewriting the Article. A mismatch returns
no replacement content, so a newer revision cannot masquerade as prior evidence.
Backlinks come from exact graph resolution; search is not a substitute.
