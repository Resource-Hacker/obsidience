---
type: skill
title: Using vault.read
obsidience:
  tool: '[[Tools/vault.read]]'
---

Use `vault.read` for bounded pages of exact Articles and their deterministic inbound graph references.

- Begin with `{"ref":"Folder/name"}` or batch independent first pages with `{"refs":["Folder/first","Folder/second"]}`. A batch contains 1-10 distinct Articles. Do not supply both forms, guess ambiguous titles or repeat an Article under aliases.
- Each success returns the same `Article` identity envelope, canonical ref, `view_sha256`, character range and up to 8000 view characters. Inspect each batch item's `ok` and `result`; successful neighboring items cannot fill missing evidence.
- The view includes native lifecycle (`status`, `freshness`, optional `stale_after`), Article title/body and `Accepted inbound references`. The latter displays at most 24 and states omissions. Lifecycle is document metadata, not Task execution status or verification; other authority metadata is not exposed by this view.
- Continue an incomplete Article separately with its exact `ref`, returned next `offset` and `expected_sha256` equal to its prior `view_sha256`. Batch pagination fields, if used, apply to every item. Character offsets are not byte offsets.
- A complete read covers offset zero through the explicit end with no missing ranges and the same revision. Read every needed page before using a new contextual-link endpoint. Initial pages, snippets and the last page alone are insufficient.
- Article, lifecycle or backlink changes reject the old expected hash without returning replacement content. Read offset zero without that hash only to explicitly obtain the current view, then complete its own pages. Never combine revisions as one complete read.
- Earlier consumed pages may be projected to bounded prefixes and exact recovery instructions. Recover omitted text only through the returned version-checked path; do not infer omitted facts.
- Treat only displayed exact refs as observed backlinks. A capped backlink list is not the entire graph. Stop on missing, unavailable or cancelled reads; do not substitute a similar title or invent content.
