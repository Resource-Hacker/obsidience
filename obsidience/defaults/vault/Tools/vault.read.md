---
type: tool
title: vault.read
description: Read an exact accessible Article using ref, or up to ten refs.
obsidience:
  binding: capability:vault.read
  source: obsidience/harness/capabilities/vault/read.py
---

## Runtime

Read an exact accessible Article using ref, or up to ten refs. Optional offset and expected_sha256 continue a clipped read consistently. No guessed-path fallback or other-Agent access exists. Follow the returned continuation to obtain text beyond the current range. Retain Article identity and clipping limits; reading a contract does not assign its Tools.

## Reference

Read a bounded page of an Article view using exactly one of `ref` or `refs` (1-10 distinct Article refs). Refs are nonempty, at most 500 characters and contain no control characters. Canonical aliases for the same Article are duplicate batch inputs and are rejected. `offset` defaults to 0 and is a nonnegative character offset. Optional `expected_sha256` must be the exact previously returned `view_sha256`; every nonzero offset requires it.

Each page retains its canonical ref, `view_sha256`, exact character range, total length and up to 8000 view characters. The complete view begins with native document lifecycle (`status`, `freshness`, optional `stale_after`), then contains the Article text and up to 24 deterministic inbound refs, with an omission count when needed. The revision covers Article text, lifecycle and the complete backlink snapshot, including backlinks outside the displayed bound. Expiry or backlink changes invalidate an earlier view without changing Article text. A revision mismatch returns no replacement content.

The editable Article body ends at `--- End of Article body ---`. The following `Accepted inbound references` section is generated read-only context about Articles linking TO this Article. It is not authored content or evidence of outgoing relationships. Never copy the marker or appendix into a proposal body.

Single results retain the existing Article page format. Batch results are JSON `{"results":[{"ref":"Folder/name","ok":true,"result":"the same Article page text"}]}` with honest per-item missing or stale failures. One locked graph snapshot and backlink traversal serve the whole batch. Pages total at most 80000 characters plus bounded wrapper metadata. Common offset and expected_sha256 apply to every item; normally batch initial pages, then continue each incomplete Article separately with its own returned revision.

Cancellation stops later pages. No Article is written. Complete-read evidence requires contiguous coverage from offset zero to the end of one unchanged current view. A failed version check cannot grant complete evidence; read offset zero without an expected hash to explicitly obtain the current view.
